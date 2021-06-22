#!/usr/bin/env python

import sys
import tempfile

sys.path.append('/pkg/bin')
from ztp_helper import ZtpHelpers
import socket
from contextlib import closing
import os, posixpath, subprocess
import time, json
import argparse
from ctypes import cdll
libc = cdll.LoadLibrary('libc.so.6')
_setns = libc.setns
CLONE_NEWNET = 0x40000000



LIGHTTPD_SYSVINIT="""
#!/bin/sh
#
# /etc/init.d/lighttpd_ztp
# Subsystem file for lighttpd Daemon for ZTP
# chkconfig: 2345 95 05
# description: Lighttpd ZTP Daemon
#
# processname: lighttpd_ztp 
# pidfile: /var/run/lighttpd_ztp.pid

NAME="lighttpd_ztp"
PATH=/sbin:/bin:/usr/sbin:/usr/bin
PIDFILE=/var/run/$NAME.pid
DAEMON=/usr/sbin/lighttpd
DESC="Lighttpd Web Server"
OPTS="-f /misc/disk1/lighttpd_ztp.conf"
DAEMON_USER="root"
VRF="global-vrf"

do_start() {
        # Return
        #   0 if daemon has been started
        #   1 if daemon was already running
        #   2 if daemon could not be started
    echo "Starting lighttpd ztp server"
        if [ -f $PIDFILE ]; then
            echo "Lighttpd ztp server already running : see $PIDFILE. Current PID: $(cat $PIDFILE)"
            return 1
        fi

        ip netns exec $VRF start-stop-daemon --start --make-pidfile  \
                          --background \
                          --pidfile $PIDFILE --quiet \
                          --user $DAEMON_USER \
                          --startas $DAEMON -- $OPTS \
                          || return 2

        echo "OK"
}

do_stop() {
        # Return
        #   0 if daemon has been stopped
        #   1 if daemon was already stopped
        #   2 if daemon could not be stopped
        #   other if a failure occurred
        ip netns exec $VRF start-stop-daemon --signal SIGTERM \
                          --stop --quiet \
                          --retry=TERM/30/KILL/5 \
                          --oknodo \
                          --pidfile $PIDFILE -- $OPTS
        RETVAL="$?"
        [ "$RETVAL" = 2 ] && return 2

        rm -f $PIDFILE
        return "$RETVAL"
          echo "OK"
}


case "$1" in
  start)
      do_start
      case "$?" in
          0|1) echo -ne "Lighttpd ztp server started successfully\n"  ;;
          2) echo -ne "Failed to start lighttpd ztp server \n" ;;
      esac
      ;;
  stop)
      do_stop
      case "$?" in
          0|1) echo -ne "Lighttpd ztp server stopped successfully\n"  ;;
          2) echo -ne "Failed to stop lighttpd ztp server \n" ;;
      esac
      ;;
  restart|force-reload)
      echo "Restarting $DESC" "$NAME"
      do_stop
      case "$?" in
          0|1)
              echo -ne "Lighttpd ZTP Server  stopped successfully.\n"
              do_start
              case "$?" in
                  0|1) echo "Lighttpd ZTP Server started successfully"  ;;
                  *) echo "Failed to start Lighttpd ztp server " ;; # Failed to start
              esac
              ;;
          *)
              # Failed to stop
              echo "Failed to stop Lighttpd ztp server"
              exit 1
          ;;
      esac
      ;;
  *)
    N=/etc/init.d/$NAME
    echo "Usage: $N {start|stop|restart|force-reload}" >&2
    exit 1
    ;;
esac
exit 0
"""


LIGHTTPD_SYSTEMD="""
# lighttpd systemd service file
#
# Copyright (c) 2018-2020 by Cisco Systems, Inc.
#

[Unit]
Description=Lightning Fast Webserver With Light System Requirements
After=xr-install.service

[Service]
# The bootup_fpd_upgrade utility requires cookie configuration before
# xr-install service.  This requires the lighttpd server to be started
# before the xr-install service.  However, CSCvs58984 means that there's 
# no way to move the lighttpd service earlier.  To workaround this, the
# lighttpd service is started from xr-install manually.
#
ExecStartPre=/usr/bin/env ip netns exec global-vrf /usr/sbin/lighttpd -t -f /misc/disk1/lighttpd_ztp.conf
ExecStart=/usr/bin/env ip netns exec global-vrf /usr/sbin/lighttpd -D -f /misc/disk1/lighttpd_ztp.conf
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure

[Install]
WantedBy=multi-user.target
"""


class ShiftZTPServer(ZtpHelpers):

    def __init__(self,
                 syslog_file=None,
                 syslog_server=None,
                 syslog_port=None):

        super(ShiftZTPServer, self).__init__(syslog_file=syslog_file,
                                       syslog_server=syslog_server,
                                       syslog_port=syslog_port)

        self.root_lr_user = "ztp-user"

        xr_arch_check = self.getXrArch()
        if xr_arch_check["status"] == "success":
            self.xr_arch = xr_arch_check["output"]
        else:
            self.syslogger.info("Failed to Get XR arch, defaulting to XR")
            self.xr_arch = "XR"

        
        self.dhcp_server_config_list=[]



    def set_lighttpd_config(self, port=8080, server_root="/misc/disk1/ztp"):
        self.httpd_port=int(port)
        self.httpd_server_root=server_root

        self.lighttpd_config="""
        # Copyright (c) 2018-2019 by Cisco Systems, Inc.
        # All rights reserved.
        server.port                 = {lighttpd_port}
        server.modules              = (
                                        "mod_access",
                                        "mod_accesslog",
                                        "mod_dirlisting" )
        server.document-root        = "{lighttpd_server_root}"
        server.errorlog             = "/var/log/ztp.lighttpd.error.log"
        accesslog.filename          = "/var/log/ztp.lighttpd.access.log"
        debug.log-request-handling  = "disable"
        url.access-deny             = ( "~", ".inc" )
        server.pid-file             = "/var/run/lighttpd_ztp.pid"
        #index-file.names            = ( "index.txt" )
        dir-listing.activate        = "enable" # Enable recursive get
        """.format(lighttpd_port=self.httpd_port, 
                   lighttpd_server_root=self.httpd_server_root)

        try:
            os.remove("/misc/disk1/lighttpd_ztp.conf")
        except Exception as e:
            self.syslogger.info("Failed to remove lighttpd_config file, ignoring...")
        with open("/misc/disk1/lighttpd_ztp.conf","w") as lighttpd_config:
                lighttpd_config.writelines(self.lighttpd_config)

    def getXrArch(self):
        # Get the current active RP node-name
        exec_cmd = "show version"
        show_version = self.xrCLI(cmd=exec_cmd)

        if show_version["status"] == "error":
             self.syslogger.info("Failed to get show  version output from XR")
             return {"status" : "error", "output": "", "error": "Failed to get show  version output from XR"}
        else:
            try:
                xr_arch_marker = show_version["output"][0].split(" ")[-1:][0]
                if xr_arch_marker == "LNT":
                    return {"status": "success", "output": "XR-LNT", "error": ""}
                else:
                    return {"status": "success", "output": "XR", "error": ""}
            except Exception as e:
                self.syslogger.info("Failed to get Active RP from show redundancy summary output")
                return {"status" : "error", "output" : "", "error": str(e)}



    def xrCLI(self, cmd):
        cmd = 'source /pkg/etc/xr_startup_envs.sh && export PATH=/pkg/sbin:/pkg/bin:${PATH} && ip netns exec xrnns /pkg/bin/xr_cli -n "%s"' % cmd
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
        out, err = process.communicate()
        if process.returncode:
            status = "error"
            output = "Failed to get command output"
        else:
            status = "success"
            output_list = [] 
            output = ""
            for line in out.splitlines():
                fixed_line = line.replace("\n", " ").strip()
                output_list.append(fixed_line)
                if "% Invalid input detected at '^' marker." in fixed_line:
                    status = "error"
                output = filter(None, output_list)  # Removing empty items 
        return {"status": status, "output": output} 



    def run_bash(self, cmd=None, vrf="global-vrf", pid=1):
        with open(self.get_netns_path(nsname=vrf,nspid=pid)) as fd:
            self.setns(fd, CLONE_NEWNET)

            if self.debug:
                self.logger.debug("bash cmd being run: "+cmd)
            ## In XR the default shell is bash, hence the name
            if cmd is not None:
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
                out, err = process.communicate()
                if self.debug:
                    self.logger.debug("output: "+out)
                    self.logger.debug("error: "+err)
            else:
                self.syslogger.info("No bash command provided")
                return {"status" : 1, "output" : "", "error" : "No bash command provided"}

            status = process.returncode

            return {"status" : status, "output" : out, "error" : err}


    def setup_http_server(self, port=8080, server_root="/misc/disk1/ztp", persistance=False):
        self.set_lighttpd_config(port=port, server_root=server_root)
        self.persistance = persistance
        if self.xr_arch == "XR-LNT":
            self.lighttpd_service = LIGHTTPD_SYSTEMD
            self.service_file="/etc/systemd/system/lighttpd_ztp.service"
            self.load_service="systemctl daemon-reload"
            self.persistance="systemctl enable lighttpd_ztp.service"
            self.remove_persistance="systemctl disable lighttpd_ztp.service"
            self.start_service_cmd ="systemctl start lighttpd_ztp"
            self.stop_service_cmd = "systemctl stop lighttpd_ztp"
        else:
            self.lighttpd_service = LIGHTTPD_SYSVINIT
            self.service_file="/etc/init.d/lighttpd_ztp"
            self.persistance="chkconfig --add lighttpd_ztp"
            self.remove_persistance="chkconfig --del lighttpd_ztp"
            self.load_service="chmod +x /etc/init.d/lighttpd_ztp"
            self.start_service_cmd ="service lighttpd_ztp start"
            self.stop_service_cmd = "service lighttpd_ztp stop"
        

        try:
            with open(self.service_file,"w") as service_file:
                service_file.writelines(self.lighttpd_service)

            cmd_run = self.run_bash(self.load_service)
            if not cmd_run["status"]:
                self.syslogger.info("Lighttpd service set up successfully")
                if self.persistance:
                    cmd_run = self.run_bash(self.persistance)
                    if not cmd_run["status"]:
                        self.syslogger.info("Lighttpd service set up to run persistently")
                    else:
                        self.syslogger.info("Failed to setup lighttpd service persistently")
                return{"status": "success"}
            else:
                self.syslogger.info("Failed to setup lighttpd service")
                return{"status": "error"}
        except Exception as e:
            self.syslogger.info("Failed to create lighttpd service file, error: "+str(e))
            return{"status": "error"}


    def remove_http_server(self):
        if self.persistance:
            cmd_run = self.run_bash(self.remove_persistance)
            if not cmd_run["status"]:
                self.syslogger.info("Lighttpd service persistance disabled")
            else:
                self.syslogger.info("Failed to disable lighttpd service persistance")
        #Remove the httpd server configs
        try:
            os.remove(self.service_file)
        except Exception as e:
            self.syslogger.info("Failed to remove lighttpd_ztp service file, ignoring...")

    def check_httpd_server(self):
        # Check if the intended port is open
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            if sock.connect_ex(("127.0.0.1", self.httpd_port)) == 0:
                self.syslogger.info("Lighttpd Port is open, server is running")
                return {"status": "success"}
            else:
                self.syslogger.info("Lighttpd Port is not open, server not running")
                return {"status": "error"}


    def http_server_action(self, action=None):
        if action is None:
            self.syslogger.info("No action specified, skipping...")
            return {"status": "error"}
        elif action == "start":
            self.syslogger.info("Starting Lighttpd server")
            cmd_run = self.run_bash(self.start_service_cmd)
            if not cmd_run["status"]:
                self.syslogger.info("Lighttpd service started")
                server_check = self.check_httpd_server()
                if server_check["status"] == "error":
                    return {"status": "error"}
                else:    
                    return {"status": "success"}
            else:
                self.syslogger.info("Failed to start lighttpd service")
                return {"status": "error"}
        elif action == "stop":
            self.syslogger.info("Stopping Lighttpd server")
            cmd_run = self.run_bash(self.stop_service_cmd)
            if not cmd_run["status"]:
                self.syslogger.info("Lighttpd service stopped")               
            else:
                self.syslogger.info("Failed to stop lighttpd service")
                return {"status": "error"}

            


    def dhcp_server_address_pool(self, min_addr="", max_addr="", dhcp_vrf="default"):
        self.pool_config = """!
                    pool vrf {dhcp_vrf} ipv4 ZTP
                     address-range {min_addr} {max_addr}
                    !
                    """.format(dhcp_vrf=dhcp_vrf,
                               min_addr=min_addr,
                               max_addr=max_addr)

        self.dhcp_server_config_list.append(self.pool_config)

    def dhcp_server_profile(self, bootfile_url=None):
        if bootfile_url is None:
            self.syslogger.info("bootfile_url not specified, aborting...")
            return{"status": "error"}

        self.dhcp_server_profile_cfg = """
                    dhcp ipv4
                     profile ztp server
                      lease infinite
                      bootfile "{bootfile_url}"
                      pool ZTP
                      option 43 hex 010a6578722d636f6e666967020100
                     """.format(bootfile_url=bootfile_url)
        self.dhcp_server_config_list.append(self.dhcp_server_profile_cfg)
        return{"status": "success"}


    def dhcp_server_interface(self, bind_intf=None, dhcp_server_ip=None, dhcp_server_ip_netmask="/30"):
   
        if bind_intf is None:
            self.syslogger.info("No interface provided, skipping...")
            return

        if dhcp_server_ip is None:
            self.syslogger.info("No dhcp_server_ip provided, skipping...")
            return


        intf_bind_list=""

        dhcp_server_header_cfg = "!\ndhcp ipv4\n"

        intf_bind_list=[dhcp_server_header_cfg]

        #for interface in intf_list:
        #    intf_bind="  interface "+str(interface)+" server profile ztp\n"      
        #    intf_bind_list.append(intf_bind)
        intf_bind="  interface "+str(bind_intf)+" server profile ztp\n"
        intf_bind_list.append(intf_bind)
        end_marker = "!\n"
        intf_bind_list.append(end_marker)
            
        dhcp_server_intf_bind = ''.join(intf_bind_list)
        result = self.xrapply_string(dhcp_server_intf_bind)
        if result["status"] == "error":
            self.syslogger.info("Failed to apply DHCP interface bind config to router %s"+json.dumps(result))

        # Configure the DHCP Server IP on the interface 
        dhcp_server_intf_cfg = "interface "+str(bind_intf)+"\n  ipv4 address "+str(dhcp_server_ip)+str(dhcp_server_ip_netmask)+"\n  no shutdown\n!\n"
        result = self.xrapply_string(dhcp_server_intf_cfg)
        if result["status"] == "error":
            self.syslogger.info("Failed to apply DHCP interface bind config to router %s"+json.dumps(result))
        return result


    def config_dhcp_server(self):
        self.dhcp_server_config = ''.join(self.dhcp_server_config_list)

        with tempfile.NamedTemporaryFile(delete=True) as f:
            f.write("%s" % self.dhcp_server_config)
            f.flush()
            f.seek(0)
            result = self.xrapply(f.name)

        if result["status"] == "error":

            self.syslogger.info("Failed to apply DHCP server config to router %s"+json.dumps(result))

        return result



    def remove_dhcp_server_config(self, dhcp_vrf="default", bind_intf=None):
        if bind_intf is not None:
            no_bind_intf="!\ninterface "+str(bind_intf)+"\n  no ipv4 address\n!"
        else:
            no_bind_intf=""

        no_dhcp_server="""
                        !
                        no dhcp ipv4
                        !
                        no pool vrf {dhcp_vrf} ipv4 ZTP
                        """.format(dhcp_vrf=dhcp_vrf)

        no_config="".join([no_bind_intf, no_dhcp_server])
        with tempfile.NamedTemporaryFile(delete=True) as f:
            f.write("%s" % no_config)
            f.flush()
            f.seek(0)
            result = self.xrapply(f.name)

        if result["status"] == "error":

            self.syslogger.info("Failed to apply DHCP server config to router %s"+json.dumps(result))

        return result




if __name__ == "__main__":

    # Create an Object of the child class, syslog parameters are optional. 
    # If nothing is specified, then logging will happen to local log rotated file.
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--ignore-dhcp-server', action='store_true', dest='ignore_dhcp_server',
                    help='Skip DHCP server configuration and only manage the http server')
    parser.add_argument('-b', '--persistent-httpd-service', action='store_true', dest='persistent_httpd_service',
                    help='If option is specified, httpd service will be made persistent across reloads')
    parser.add_argument('-d', '--dhcp-intf', dest='dhcp_intf', default="",
                    help='Specify the interface to enable the DHCP server on. If not specified, only the DHCP server will be configured, without binding to any interface')
    parser.add_argument('-p','--httpd-port', dest='httpd_port', default=8080,
                    help='Specify port on which the httpd server will run')
    parser.add_argument('-r','--server-root', action='append', dest='httpd_server_root', default="/misc/disk1/ztp",
                    help='Specify root directory for the httpd server')
    parser.add_argument('-a','--action', dest='action', default="start",
                        help='Action options are "start" and "stop"')
    parser.add_argument('-c', '--dhcp-client-ip', dest='dhcp_client_ip', default="1.1.1.2",
                        help='Specify the default dhcp client ip for the ZTP node')
    parser.add_argument('-s', '--dhcp-server-ip', dest='dhcp_server_ip', default="1.1.1.1",
                        help='Specify the default dhcp server ip for the ZTP node')
    parser.add_argument('-z', '--ztp-script-filename', dest='ztp_script_filename', default="ztp_script.py",
                        help='Specify the filename of the ZTP script to be used in bootfilename option for the next ZTP node')
    parser.add_argument('-v', '--dhcp-server-vrf', dest='dhcp_server_vrf', default="default",
                        help='Specify the dhcp server vrf')

    argobj= parser.parse_args()

    ztp_server = ShiftZTPServer()

    if not argobj.ignore_dhcp_server:
        ztp_server.dhcp_server_address_pool(min_addr=argobj.dhcp_client_ip,
                                            max_addr=argobj.dhcp_client_ip,
                                            dhcp_vrf=argobj.dhcp_server_vrf)
        profile_setup = ztp_server.dhcp_server_profile(bootfile_url="http://"+str(argobj.dhcp_server_ip)+":"+str(argobj.httpd_port)+"/"+str(argobj.ztp_script_filename))
        if profile_setup["status"] == "error":
            ztp_server.syslogger.info("Failed to setup DHCP server profile, exiting...")
            sys.exit(1)


    # Now setup the lighttpd server

    httpd_server=ztp_server.setup_http_server(port=argobj.httpd_port, 
                      server_root=argobj.httpd_server_root,
                      persistance=argobj.persistent_httpd_service)
 
    if httpd_server["status"] == "success":
        ztp_server.syslogger.info("Httpd service successfully set up")
    else:
        ztp_server.syslogger.info("Failed to set up HTTPD server, exiting...")
        sys.exit(1)


    # Based on the action specified, start or stop the service

    if argobj.action=="start":
        if not argobj.ignore_dhcp_server:
            config_dhcp = ztp_server.config_dhcp_server()

            if config_dhcp["status"] == "success":
                ztp_server.syslogger.info("DHCP server successfully configured")
            else:
                ztp_server.syslogger.info("Failed to configure DHCP server in XR, exiting..")
                sys.exit(1)

            if argobj.dhcp_intf != "":
                bind_dhcp = ztp_server.dhcp_server_interface(bind_intf=argobj.dhcp_intf,dhcp_server_ip=argobj.dhcp_server_ip)
                if config_dhcp["status"] == "success":
                    ztp_server.syslogger.info("DHCP server bound to interfaces: "+str(argobj.dhcp_intf))
                else:
                    ztp_server.syslogger.info("Failed to bind DHCP server to specified interfaces, exiting..")
                    sys.exit(1)


        # Stop any previously running instance of the http server before starting again
        http_server_run = ztp_server.http_server_action(action="stop")
        http_server_run = ztp_server.http_server_action(action="start")
 
    elif argobj.action =="stop":
        if not argobj.ignore_dhcp_server:
            if argobj.dhcp_intf != "":
                config_dhcp = ztp_server.remove_dhcp_server_config(bind_intf=argobj.dhcp_intf)
            else:
                config_dhcp = ztp_server.remove_dhcp_server_config()

            if config_dhcp["status"] == "success":
                ztp_server.syslogger.info("DHCP server successfully unconfigured")
            else:
                ztp_server.syslogger.info("Failed to unconfigure DHCP server in XR, exiting..")
                sys.exit(1)
  
        ztp_server.http_server_action(action="stop")
        ztp_server.remove_http_server()