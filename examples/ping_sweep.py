"""Example: ping every device from one PC and print a reachability table.

    python examples/ping_sweep.py PC0

Uses only the standard library. The gateway must be running and PT connected.
"""
import json
import re
import sys
import urllib.request

API = "http://127.0.0.1:7532/api/pt/tool/"


def call(tool, args, timeout=180):
    req = urllib.request.Request(API + tool, data=json.dumps(args).encode(),
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def main(src):
    devices = call("listDevices", {})["result"]
    devices = devices.get("result", devices) if isinstance(devices, dict) else devices
    for d in devices:
        ip = d.get("ip")
        if not ip or ip in ("null", "0.0.0.0") or d["name"] == src:
            continue
        out = call("pcCommand", {"deviceName": src, "command": f"ping -n 2 {ip}", "wait": 30})["result"]["output"]
        # count real echo replies only: "Reply from <gw>: Destination host unreachable" is not one
        replies = len(re.findall(rf"Reply from {re.escape(ip)}: bytes=", out))
        why = "unreachable" if "unreachable" in out else ("timeout" if "timed out" in out else "")
        print(f"{src} -> {d['name']:20} {ip:15} {'reply' if replies else 'no reply':9} {why}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "PC0")
