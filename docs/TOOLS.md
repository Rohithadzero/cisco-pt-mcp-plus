# Tool reference

Call any tool with `POST /api/pt/tool/<name>` and a JSON body of arguments, or through the MCP proxy.
`?` marks an optional argument. Generated from `ptgateway/legacy_schemas.py` and `ptgateway/tools.py`.

## New tools (16): implemented as JavaScript through the plugin's `ptEval` hook

| Tool | Arguments | What it does |
|---|---|---|
| `ptEval` | `code` | Run a JavaScript function body inside Packet Tracer's script engine (must return JSON-serialisable data). Expert escape hatch. |
| `probeProcesses` | `deviceName`, `names`? | Report which Device.getProcess names exist on a device (debug). |
| `setServerService` | `deviceName`, `service`, `enabled`? | Turn a Server-PT service on/off: http, https, dns, dhcp, syslog, ntp, iot, ftp, tftp, email. |
| `listDhcpPools` | `deviceName` | List DHCP pools on a Server-PT. |
| `setDhcpPool` | `deviceName`, `poolName`, `gateway`, `dns`, `startIp`, `mask`, `maxUsers` | Create or update a DHCP pool on a Server-PT (serverPool can only be updated). |
| `removeDhcpPool` | `deviceName`, `poolName` | Remove a DHCP pool. |
| `addDnsRecord` | `deviceName`, `name`, `ip` | Enable DNS on a Server-PT and add an A record. |
| `listDnsRecords` | `deviceName` | List DNS entries on a Server-PT. |
| `setHttpPage` | `deviceName`, `content`, `path`?, `https`? | Enable HTTP(+HTTPS) on a Server-PT and set a page's HTML. |
| `getHostIp` | `deviceName`, `port`? | Read IP/mask/MAC/DHCP flag of an end-device port. |
| `renewDhcp` | `deviceName`, `port`?, `wait`? | Switch an end device to DHCP, request a lease and return the address. |
| `pcCommand` | `deviceName`, `command`, `wait`?, `settle`? | Type a command into a PC/laptop/server Command Prompt (ping, ipconfig, telnet, ssh, nslookup, tracert) and return its output. Realtime mode. |
| `pcSession` | `deviceName`, `lines`, `wait`? | Send several lines to an end-device prompt in order (e.g. telnet, password, exit). |
| `iosExec` | `deviceName`, `command`, `wait`? | Run an exec-mode IOS command (e.g. show access-lists) on a router/switch and return console output. |
| `httpGet` | `deviceName`, `url`, `wait`?, `https`? | Open a URL in an end device's web browser (PT HttpClient) and return page content. |
| `listDevices` | – | List every device with model, type, canvas position, power and Fa0 IP. |

## Stock cisco-pt-mcp tools (18): forwarded unchanged to the plugin

| Tool | Arguments | What it does |
|---|---|---|
| `addDevice` | `deviceName`, `deviceModel`, `x`, `y` | Add a network device to the workspace. Call getNetwork first if unsure whether the chosen deviceName is already taken; names must be unique. |
| `addModule` | `deviceName`, `slot`, `model` | Add an interface module to a device. Powers the device off, installs the module, powers it back on. |
| `addLink` | `device1Name`, `device1Interface`, `device2Name`, `device2Interface`, `linkType` | Connect two devices with a cable. Both interfaces must be free (in_use=false in getNetwork output). If unsure, call getNetwork first. |
| `removeDevice` | `deviceNames` | Remove one or more devices from the workspace. |
| `removeLink` | `links` | Remove one or more cables. Each entry identifies one endpoint of the link. |
| `configurePcIp` | `deviceName`, `dhcpEnabled`?, `ipaddress`?, `subnetMask`?, `defaultGateway`?, `dnsServer`? | Configure IP settings on a PC or end device. |
| `configureIosDevice` | `deviceName`, `commands` | Execute IOS commands on a router or switch. Commands run from global config and are saved with 'write memory'. |
| `getNetwork` | – | Snapshot of the entire workspace: every device, its interfaces (with in_use flags), and every cable. Call this before addLink or removeDevice when unsure of current state. |
| `getDeviceInfo` | `deviceName` | Detailed info about one device, including interfaces and incident links. |
| `setSimulationMode` | `toSimMode` | Switch Packet Tracer between simulation mode and realtime mode. Simulation mode is required before sending PDUs or stepping through traffic. |
| `getSimulationStatus` | – | Query the current simulation state: mode (realtime or simulation), elapsed simulation time, PDU frame count, and current frame index. |
| `stepSimulation` | `direction`, `steps`? | Step the simulation forward or backward, or reset it entirely. PT must already be in simulation mode (use setSimulationMode first). |
| `sendPdu` | `sourceDevice`, `destinationDevice` | Add an ICMP ping PDU between two devices using PT's native Simple PDU mechanism. Automatically enables simulation mode if not already active. Use stepSimulation to advance and getPduResults to check if the ping succeeded. |
| `renameDevice` | `deviceName`, `newName` | Rename an existing device. The new name must be unique in the workspace. |
| `moveDevice` | `deviceName`, `x`, `y` | Move a device to new coordinates on the logical workspace canvas. |
| `setPower` | `deviceName`, `power` | Power a device on or off. |
| `getPduResults` | `types`? | Read the outcome of PDUs in the current simulation — source, destination, traffic type, and status (accepted/dropped/in_transit/etc). Call after stepSimulation to verify connectivity. Use the types filter to show only ICMP, TCP, etc. and hide STP/DTP background noise. |
| `getCommandLog` | `deviceName`?, `limit`? | Read the IOS command history logged by Packet Tracer. Optionally filter by device name and cap the number of returned entries. |
