## Basic Instructions

To utilize this playbook, peform the following steps:

1) On the Takeoff Node for the Ring (AG1 - see image below), Copy the ztp script: `ztp_script.py` to the following folder on the router harddisk: `/misc/disk1/ztp/`

    ![](/images/Slide1.jpeg)  
    
2) Copy the ondemand script: `shifting_ztp_server.py` that will be used to setup the dhcp + http server on each node to the hardisk location:  `/misc/disk1`

3) The ondemand script is very flexible and can be invoked from the router's CLI to set up the DHCP and HTTP server on each node when needed. You can also skip setting up the dhcp-server and only bring up the http sever using this script. The options available to use can be checked using the "-h" option:

  ```
  RP/0/RP0/CPU0:AG1#bash -c python /misc/disk1/shifting_ztp_server.py -h   
  Tue Jun 22 22:23:11.661 UTC
  # netconf_client_ztp_lib - version 1.2 #
  usage: shifting_ztp_server.py [-h] [-i] [-b] [-d DHCP_INTF] [-p HTTPD_PORT]
                                [-r HTTPD_SERVER_ROOT] [-a ACTION]
                                [-c DHCP_CLIENT_IP] [-s DHCP_SERVER_IP]
                                [-z ZTP_SCRIPT_FILENAME] [-v DHCP_SERVER_VRF]

  optional arguments:
    -h, --help            show this help message and exit
    -i, --ignore-dhcp-server
                          Skip DHCP server configuration and only manage the
                          http server
    -b, --persistent-httpd-service
                          If option is specified, httpd service will be made
                          persistent across reloads
    -d DHCP_INTF, --dhcp-intf DHCP_INTF
                          Specify the interface to enable the DHCP server on. If
                          not specified, only the DHCP server will be
                          configured, without binding to any interface
    -p HTTPD_PORT, --httpd-port HTTPD_PORT
                          Specify port on which the httpd server will run
    -r HTTPD_SERVER_ROOT, --server-root HTTPD_SERVER_ROOT
                          Specify root directory for the httpd server
    -a ACTION, --action ACTION
                          Action options are "start" and "stop"
    -c DHCP_CLIENT_IP, --dhcp-client-ip DHCP_CLIENT_IP
                          Specify the default dhcp client ip for the ZTP node
    -s DHCP_SERVER_IP, --dhcp-server-ip DHCP_SERVER_IP
                          Specify the default dhcp server ip for the ZTP node
    -z ZTP_SCRIPT_FILENAME, --ztp-script-filename ZTP_SCRIPT_FILENAME
                          Specify the filename of the ZTP script to be used in
                          bootfilename option for the next ZTP node
    -v DHCP_SERVER_VRF, --dhcp-server-vrf DHCP_SERVER_VRF
                          Specify the dhcp server vrf

    RP/0/RP0/CPU0:AG1#


  ```
 
 4) For example, in order to setup the http server on port 57200 and DHCP server to provide options for downstream node and listen on interface TenGigE0/0/0/17, just run the following command once on the takeoff node:

    ```
    RP/0/RP0/CPU0:AG1#bash -c python /misc/disk1/shifting_ztp_server.py -p 57200 -d "TenGigE0/0/0/17"
    Tue Jun 22 22:26:30.502 UTC
    # netconf_client_ztp_lib - version 1.2 #
    Building configuration...
    Building configuration...

    RP/0/RP0/CPU0:AG1#
    ```
    Once the ondemand script is executed, the following DHCP server config will appear on the take-off node:
    
    ```
    RP/0/RP0/CPU0:AG1#
    RP/0/RP0/CPU0:AG1#show run dhcp ipv4
    Tue Jun 22 22:28:53.203 UTC
    dhcp ipv4
     profile ztp server
      lease infinite
      bootfile "http://1.1.1.1:57200/ztp_script.py"
      pool ZTP
      option 43 hex 010a6578722d636f6e666967020100
     !
     interface TenGigE0/0/0/17 server profile ztp
    !

    RP/0/RP0/CPU0:AG1#show run pool     
    Tue Jun 22 22:28:55.576 UTC
    pool vrf default ipv4 ZTP
     address-range 1.1.1.2 1.1.1.2
    !

    RP/0/RP0/CPU0:AG1#show run int TengigE 0/0/0/17
    Tue Jun 22 22:29:10.600 UTC
    interface TenGigE0/0/0/17
     ipv4 address 1.1.1.1 255.255.255.252
    !

    RP/0/RP0/CPU0:AG1#

    ```

    The HTTP server will be start listening on the port specified and to check that the port is open, run the following command:
    
    ```
    RP/0/RP0/CPU0:AG1#bash -c netstat -nlp | grep lighttpd  
    Tue Jun 22 22:32:09.536 UTC
    tcp        0      0 0.0.0.0:57200           0.0.0.0:*               LISTEN      29921/lighttpd  

    RP/0/RP0/CPU0:AG1#
    
    ```
    
 5) At this stage, the takeoff node is ready to serve the downstream nodes performing ZTP. 
 6) Since this is a "shifting ZTP server" technique. When the CSS1 node performs ZTP and is available on the /30 IP address, the operator would gain remote access and configure a routable IP address on the upstream node instead of the /30 IP so it may be reused.
 
 7) Lastly, the ZTP script: `ztp_script.py` is designed to set up everything on the CSS1 node post ZTP identical to the node AG1. Therefore, to bootstrap node CSS2, simply run the same steps as above to start the DHCP + HTTP server on CSS1 making it the new takeoff node, before moving on to CSS2 and so on ...
    
