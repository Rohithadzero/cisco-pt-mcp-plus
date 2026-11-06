# cisco-pt-mcp-plus

REST + MCP gateway for **Cisco Packet Tracer 9**. It's a small patch to the
[cisco-pt-mcp](https://github.com/muhammadbalawal/cisco-pt-mcp) script module plus a Python gateway.
Together they let an AI agent (or curl, or a script) **configure servers and read real output** from a running
Packet Tracer instead of just building topologies.

```
 Claude / Cursor / any MCP client          curl / Python scripts
            │ stdio                                 │ HTTP
            ▼                                       ▼
   ptgateway.mcp_proxy  ──HTTP──►  ptgateway (aiohttp, 127.0.0.1:7532)
                                     │  REST  /api/pt/tool/<name>
                                     │  Socket.IO (cisco-pt-mcp wire protocol)
                                     ▼
                     Packet Tracer ── patched cisco-pt-mcp module
                                       userfunctions.js + ptEval(code)
                                       interface.js  → MCP_URL :7532
```

## Why

The stock cisco-pt-mcp module exposes **18 fixed functions** (add devices, cable, push IOS config, send a
simulation PDU). That covers building a lab, but not configuring or checking one:

| Needed | Stock cisco-pt-mcp | This repo |
|---|---|---|
| Read `show ip route` / `show access-lists` output | ✗ (`configureIosDevice` returns no output) | `iosExec` |
| Real `ping` / `telnet` / `ssh` / `nslookup` output from a PC | ✗ (only simulation PDUs, results garbled in PT 9) | `pcCommand`, `pcSession` |
| Server-PT: DHCP pools, DNS records, web pages, service on/off | ✗ | `setDhcpPool`, `addDnsRecord`, `setHttpPage`, `setServerService` |
| Renew a DHCP lease and get the address | ✗ | `renewDhcp`, `getHostIp` |
| Open a page in a PC's browser | ✗ | `httpGet` |
| Anything else in PT's script API (open/save `.pkt`, …) | ✗ | `ptEval` |
| Several clients share one PT (MCP + scripts + curl) | one MCP process owns PT | one gateway, REST for everyone |

The trick: add **one** generic function, `ptEval(code)`, to the plugin. It runs a JS function body inside PT's
script engine. Every new tool is then a short JS snippet built in Python (`ptgateway/tools.py`), with no more
plugin edits per feature.

Built while automating a 4-design hospital network project in PT 9.0.1 (D0 flat → D3 micro-segmented).
The PT 9 surprises found along the way are in [`docs/PT9-NOTES.md`](docs/PT9-NOTES.md).

## Quick start

```bash
# 1. Python side
git clone https://github.com/<you>/cisco-pt-mcp-plus && cd cisco-pt-mcp-plus
python -m venv .venv && .venv/Scripts/pip install -e .      # Linux/macOS: .venv/bin/pip
python -m ptgateway                                           # or ./run.ps1 / ./run.sh

# 2. Packet Tracer side (one time): patch 2 files of the cisco-pt-mcp module
#    -> docs/INSTALL-PLUGIN.md   (Info tab -> Save, then Stop/Start the module)
#    then: Extensions -> Packet Tracer MCP   => "connected"

# 3. Check
curl http://127.0.0.1:7532/api/pt/status
```

### Use it from an MCP client

```bash
claude mcp add packet-tracer -- <path-to>/.venv/Scripts/python -m ptgateway.mcp_proxy
```

The proxy lists all 34 tools (18 stock + 16 new) and forwards each call to the gateway.
`PTGATEWAY_URL` overrides the default `http://127.0.0.1:7532`.

### Use it from code

```bash
curl -X POST http://127.0.0.1:7532/api/pt/tool/iosExec \
     -H "content-type: application/json" \
     -d '{"deviceName":"R1","command":"show ip route"}'
```

```python
import json, urllib.request
def pt(tool, **args):
    r = urllib.request.urlopen(urllib.request.Request(
        f"http://127.0.0.1:7532/api/pt/tool/{tool}", json.dumps(args).encode(),
        {"content-type": "application/json"}), timeout=180)
    return json.loads(r.read())

print(pt("pcCommand", deviceName="PC0", command="ping 10.0.0.1")["result"]["output"])
```

More: [`examples/rest_examples.sh`](examples/rest_examples.sh), [`examples/ping_sweep.py`](examples/ping_sweep.py).

## Tools

**New (via `ptEval`):** `ptEval`, `iosExec`, `pcCommand`, `pcSession`, `httpGet`, `renewDhcp`, `getHostIp`,
`listDevices`, `setServerService`, `setDhcpPool`, `listDhcpPools`, `removeDhcpPool`, `addDnsRecord`,
`listDnsRecords`, `setHttpPage`, `probeProcesses`.

**Stock (forwarded):** `addDevice`, `addModule`, `addLink`, `removeDevice`, `removeLink`, `renameDevice`,
`moveDevice`, `setPower`, `configurePcIp`, `configureIosDevice`, `getNetwork`, `getDeviceInfo`,
`setSimulationMode`, `getSimulationStatus`, `stepSimulation`, `sendPdu`, `getPduResults`, `getCommandLog`.

Arguments for each tool are listed in [`docs/TOOLS.md`](docs/TOOLS.md).

## Layout

```
ptgateway/
  server.py          aiohttp app: /api/pt/status, /api/pt/tools, POST /api/pt/tool/{name}
  bridge.py          Socket.IO server speaking the cisco-pt-mcp wire protocol (one call at a time)
  tools.py           16 composite tools = JS snippets sent through ptEval
  mcp_proxy.py       stdio MCP server -> REST
  legacy_schemas.py  the 18 stock tool schemas (from cisco-pt-mcp)
  selftest.py        fake PT plugin + REST round-trip checks (no Packet Tracer needed)
plugin/              the full module source; only userfunctions.js and interface/interface.js differ from upstream
docs/                INSTALL-PLUGIN.md, TOOLS.md, PT9-NOTES.md
examples/            curl + Python examples
```

## Test without Packet Tracer

```bash
python -m ptgateway --port 9532 &
PTGATEWAY_URL=http://127.0.0.1:9532 python -m ptgateway.selftest   # 7 PASS lines
```

## Security

`ptEval` runs arbitrary JavaScript inside Packet Tracer, and the gateway has no auth. **Keep it on loopback**
(the default). It warns if you bind to anything else. Don't expose port 7532.

## Other projects

If you need a full topology generator with ~80+ tools, use
[Mats2208/MCP-Packet-Tracer](https://github.com/Mats2208/MCP-Packet-Tracer). It covers server DHCP/DNS/HTTP,
PC commands and a raw-JS escape hatch on its own extension.
This repo is the small option: if you already use **cisco-pt-mcp**, replace two files and you get output
reading and server/service control, plus the PT 9 notes.
See also [caixax/packet-tracer-mcp](https://github.com/caixax/packet-tracer-mcp) and
[cleonte/MCP_Packet_Tracer](https://github.com/cleonte/MCP_Packet_Tracer).

## Credits & license

MIT. `plugin/`, `ptgateway/legacy_schemas.py` and the wire protocol in `ptgateway/bridge.py` come from
[cisco-pt-mcp](https://github.com/muhammadbalawal/cisco-pt-mcp) © 2026 Muhammad Balawal (MIT).
Cisco and Packet Tracer are trademarks of Cisco Systems, Inc. Not affiliated with Cisco.
