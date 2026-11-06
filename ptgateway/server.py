"""ptgateway: Socket.IO bridge + REST API for Cisco Packet Tracer.

The patched cisco-pt-mcp script module (plugin/) runs inside Packet Tracer and
connects to this server as a Socket.IO client. Every tool is then reachable
over plain HTTP:

    GET  /api/pt/status          connected?, recent calls
    GET  /api/pt/tools           tool names (18 stock + 16 composite)
    POST /api/pt/tool/{name}     JSON body = tool arguments

Run:  python -m ptgateway [--port 7532] [--host 127.0.0.1]
The plugin's MCP_URL (plugin/interface/interface.js) must point at the same port.
Binds to loopback by default: anything that can reach this port can run code
inside Packet Tracer (ptEval).
"""

from __future__ import annotations

import argparse
import json
import logging

from aiohttp import web

from .bridge import PTBridge
from .tools import COMPOSITE_SCHEMAS, LEGACY_TOOLS, PTTools


def ok(data, status: int = 200) -> web.Response:
    return web.Response(text=json.dumps(data, default=str), status=status, content_type="application/json")


def build_app(tool_timeout: float = 90.0) -> web.Application:
    app = web.Application(client_max_size=8 * 1024 * 1024)
    bridge = PTBridge(app, tool_timeout=tool_timeout)
    tools = PTTools(bridge)

    async def status(_req: web.Request) -> web.Response:
        return ok({"connected": bridge.is_connected, "since": bridge.connected_since,
                   "history": list(bridge.history)[:20]})

    async def tool_list(_req: web.Request) -> web.Response:
        return ok({"legacy": LEGACY_TOOLS, "composite": sorted(COMPOSITE_SCHEMAS)})

    async def tool_call(req: web.Request) -> web.Response:
        name = req.match_info["name"]
        try:
            args = await req.json() if req.can_read_body else {}
        except json.JSONDecodeError:
            return ok({"success": False, "error": "body must be JSON"}, 400)
        if not isinstance(args, dict):
            return ok({"success": False, "error": "body must be a JSON object"}, 400)
        return ok(await tools.call(name, args))

    app.router.add_get("/api/pt/status", status)
    app.router.add_get("/api/pt/tools", tool_list)
    app.router.add_post("/api/pt/tool/{name}", tool_call)
    return app


def main() -> None:
    ap = argparse.ArgumentParser(prog="ptgateway", description="REST + Socket.IO gateway for Cisco Packet Tracer")
    ap.add_argument("--host", default="127.0.0.1", help="bind address (default: loopback only)")
    ap.add_argument("--port", type=int, default=7532, help="must match MCP_URL in plugin/interface/interface.js")
    ap.add_argument("--timeout", type=float, default=90.0, help="seconds to wait for one PT call")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if a.host not in ("127.0.0.1", "localhost", "::1"):
        logging.warning("binding to %s: anyone who can reach it can run JavaScript inside Packet Tracer", a.host)
    print(f"ptgateway on http://{a.host}:{a.port}  (waiting for Packet Tracer: Extensions -> Packet Tracer MCP)")
    web.run_app(build_app(a.timeout), host=a.host, port=a.port, print=None)


if __name__ == "__main__":
    main()
