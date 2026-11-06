#!/usr/bin/env sh
# REST examples for ptgateway. Device names are whatever your .pkt uses.
G=http://127.0.0.1:7532/api/pt
call() { curl -s -X POST "$G/tool/$1" -H "content-type: application/json" -d "$2"; echo; }

curl -s "$G/status"; echo                                   # connected? recent calls
call listDevices '{}'                                        # name, model, position, power, Fa0 IP

# IOS: configure (stock tool) and read show output (new)
call configureIosDevice '{"deviceName":"R1","commands":"interface GigabitEthernet0/0\n ip address 10.0.0.1 255.255.255.0\n no shutdown"}'
call iosExec '{"deviceName":"R1","command":"show ip interface brief"}'

# Server-PT services
call setServerService '{"deviceName":"Server0","service":"dns","enabled":true}'
call addDnsRecord '{"deviceName":"Server0","name":"web.lab.local","ip":"10.0.0.10"}'
call setDhcpPool '{"deviceName":"Server0","poolName":"serverPool","gateway":"10.0.0.1","dns":"10.0.0.10","startIp":"10.0.0.100","mask":"255.255.255.0","maxUsers":50}'
call setHttpPage '{"deviceName":"Server0","content":"<h1>hello from ptgateway</h1>","https":false}'

# End devices: DHCP lease, real command-prompt output, browser
call renewDhcp '{"deviceName":"PC0","wait":20}'
call pcCommand '{"deviceName":"PC0","command":"ping 10.0.0.1"}'
call pcSession '{"deviceName":"PC0","lines":["telnet 10.0.0.1","cisco","show version","exit"]}'
call httpGet '{"deviceName":"PC0","url":"http://web.lab.local"}'

# Anything else: run JS in PT's script engine (must return JSON-serialisable data)
call ptEval '{"code":"return String(ipc.appWindow().getActiveFile().getSavedFilename());"}'
