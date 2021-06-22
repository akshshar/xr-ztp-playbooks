#!/bin/bash

b64_value=`cat ${PWD}/shifting_ztp_server.py | base64`
sed_param=s@ondemand_dhcp_http_script_b64=.*@ondemand_dhcp_http_script_b64=\"${b64_value}\"@
sed -i .bak "$sed_param" ${PWD}/../ztp_script.py
rm -f ${PWD}/../ztp_script.py.bak

echo "Updated ztp_script.py" 
