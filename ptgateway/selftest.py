"""End-to-end check of the ptgateway without Packet Tracer.

Starts a fake PT plugin (Socket.IO client speaking the cisco-pt-mcp wire
protocol), connects it to a running ptgateway, then drives REST calls and
checks that they travel server -> plugin -> server correctly.

Usage (gateway must be running):  python -m ptgateway.selftest
"""

from __future__ import annotations

import asyncio
import json
import sys

import httpx
import socketio

import os

BASE = os.environ.get("PTGATEWAY_URL", "http://127.0.0.1:7532")
seen: list[dict] = []


async def main() -> int:
    sio = socketio.AsyncClient()

    @sio.on("tool_call")
    async def on_call(data):
        seen.append(data)
        name, args = data["tool_name"], data["tool_input"]
        if name == "ptEval":
            code = args["code"]
            if "getIpAddress" in code:
                result = {"success": True, "result": {"ip": "10.10.20.10", "mask": "255.255.255.0", "mac": "0001.4242.0001",
                                                       "dhcp": False, "gateway": None}}
            elif "getProcess(names[i])" in code and "out[names[i]]" in code:
                result = {"success": True, "result": {"HttpServer": True, "DnsServer": True}}
            else:
                result = {"success": True, "result": {"len": 0, "text": "", "prompt": "C:\\>"}}
        elif name == "getNetwork":
            result = {"success": True, "result": {"deviceCount": 1, "devices": [{"name": "Server0"}], "connections": []}}
        else:
            result = {"success": False, "error": f"unsupported tool: {name}"}
        await sio.emit("tool_result", {"tool_call_id": data["tool_call_id"], "tool_name": name,
                                       "tool_input": args, "result": result})

    await sio.connect(BASE, transports=["websocket"])
    await asyncio.sleep(0.5)
    checks = []
    async with httpx.AsyncClient(timeout=30) as c:
        st = (await c.get(f"{BASE}/api/pt/status")).json()
        checks.append(("plugin connected", st["connected"] is True))
        r = (await c.post(f"{BASE}/api/pt/tool/getNetwork", json={})).json()
        checks.append(("legacy tool forwarded", r.get("result", {}).get("deviceCount") == 1))
        r = (await c.post(f"{BASE}/api/pt/tool/getHostIp", json={"deviceName": "Server0"})).json()
        checks.append(("composite getHostIp via ptEval", r.get("result", {}).get("ip") == "10.10.20.10"))
        r = (await c.post(f"{BASE}/api/pt/tool/probeProcesses", json={"deviceName": "Server0",
                                                                     "names": ["HttpServer", "DnsServer"]})).json()
        checks.append(("probeProcesses", r.get("result", {}).get("HttpServer") is True))
        r = (await c.post(f"{BASE}/api/pt/tool/setDhcpPool", json={"deviceName": "Server1", "poolName": "LAN10",
                                                                  "gateway": "10.10.10.1", "dns": "10.10.20.11",
                                                                  "startIp": "10.10.10.100", "mask": "255.255.255.0",
                                                                  "maxUsers": 100})).json()
        js = next((s["tool_input"]["code"] for s in reversed(seen) if s["tool_name"] == "ptEval"), "")
        checks.append(("setDhcpPool builds addNewPool JS", "addNewPool(name, \"10.10.10.1\"" in js and r.get("success")))
        r = (await c.post(f"{BASE}/api/pt/tool/nope", json={})).json()
        checks.append(("unknown tool rejected", r.get("success") is False))
        st = (await c.get(f"{BASE}/api/pt/status")).json()
        checks.append(("call history recorded", len(st["history"]) >= 4))
    await sio.disconnect()
    for name, okv in checks:
        print(("PASS " if okv else "FAIL ") + name)
    return 0 if all(v for _, v in checks) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
