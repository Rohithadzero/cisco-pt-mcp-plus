# Packet Tracer 9.0.1 script-API notes

Things we found the hard way while driving PT 9.0.1 from scripts (Windows, Nov 2026). Each one cost a debugging session.

## Script engine / IPC

| Finding | Consequence / workaround |
|---|---|
| `Device.enterCommand(cmd, "enable")` **returns** `{first: <code>, second: <output>}` and does **not** echo to the device's console line. | Read `show` output from the return value (`iosExec` does this). Scraping `getCommandLine().getOutput()` only returns boot/syslog messages. |
| `enterCommand("show running-config", …)` returns the whole config in one go (no `--More--`). | No paging handling needed. `\| include` filters often return nothing, so filter on the client side. |
| Results of the patched `ptEval` arrive **double-wrapped**: `{success, result: {success, result: value}}`. | The gateway unwraps both layers (`PTTools._eval`). |
| `getNetwork` / `getPduResults` (stock tools) return garbled connections and empty source/destination under PT 9. Interface `in_use` flags are unreliable. | Use `listDevices`, `getHostIp`, `pcCommand ping` instead. |
| `configureIosDevice` (stock) drops the line right after `no shutdown`: the link-up console message eats it. | Push each interface block as its own call, and put global commands (routes, OSPF) in separate calls. |
| Big pastes containing several `vlan N` / `name X` blocks put every name on the first VLAN. `interface range` and `interface VlanX` headers inside large chunks can be ignored on the 3560. | Push one VLAN, one interface and one ACL per call. Expand `interface range` into single interfaces. |
| ASA: `access-list NAME line N extended …` isn't accepted. | Remove the final `deny ip any any`, append the permits, then re-add the deny. |
| `ipc.appWindow().fileSaveAsNoPrompt(path, true)` saves without a dialog. `fileOpen(path)` opens; `getActiveFile().getSavedFilename()` tells you which file is open. | Use forward slashes in paths, and build the JSON with a real JSON encoder (backslashes break the parser). Save or "park" an edited file before `fileOpen`, or PT may block on a *save changes?* dialog. |

## Services and end devices

| Finding | Consequence / workaround |
|---|---|
| Server processes: `HttpServer`, `HttpsServer`, `DnsServer`, `DhcpServerMainProcess`, `SyslogServer` use `setEnable(bool)`. **`NtpServer` uses `setEnabled(bool)`**. The IoE (IoT) server exposes **no** on/off method. | `setServerService` tries both. Switch IoT on in the GUI. |
| **IoT devices register with the IoT server on TCP 31000**; only the dashboard is HTTP/80. | With least-privilege ACLs, permit `tcp … host <iot-server> eq 31000` too, or devices show the login page but never register. |
| Stock `configurePcIp` fails on IoT devices (`setDhcpFlag is not a function`). | Set IoT devices to DHCP in their Config tab (or via `ptEval` on the port). |
| Setting a static IP only on the **port** (`setIpSubnetMask`) shows the right IP but **isn't saved**: after reopening the `.pkt` the PC has 0.0.0.0. | Also call `device.setDhcpFlag(false)`, `port.setDhcpClientFlag(false)`, `device.setDefaultGateway()` and `port.setDefaultGateway()`. |
| After opening a `.pkt`, DHCP clients sit at 0.0.0.0. They ask before the switches are forwarding (STP ~30 s without PortFast) and don't retry. | Call `renewDhcp` on every client ~30 s after opening. |
| `HttpClient` exposes `http_get`, `http_post(url, body, ?)`, `getLastPageContent()`. | `httpGet` uses it. Compare content before and after: an identical page reads as "unchanged". |
| PC ping output: `Reply from <gw>: Destination host unreachable` starts with `Reply from` too. | Count a reply only if the line contains `bytes=`. |
| `ipconfig` prints the IPv6 gateway (`::`) first and the IPv4 one on the next line; a Bluetooth adapter block follows. | Parse the first adapter's IPv4 gateway. |

## Bridge / MCP

| Finding | Consequence / workaround |
|---|---|
| Only one process can own the bridge port. A second Claude window holding `cisco-pt-mcp.exe` gives `CONNECTION_CLOSED`. | Check the port owner's parent PID before killing it. |
| Opening a `.pkt` usually keeps the module connected with the patched module. The stock module often needs **Extensions → Packet Tracer MCP** again. | Re-click the extension if `/api/pt/status` says `connected: false`. |
