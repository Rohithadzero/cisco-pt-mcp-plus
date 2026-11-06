"""MCP (stdio) front for ptgateway.

An MCP client (Claude Code, Claude Desktop, Cursor, ...) starts this process.
Every tool call is forwarded over HTTP to the running gateway, so several
clients (MCP, scripts, curl) share one Packet Tracer connection.

    claude mcp add packet-tracer -- python -m ptgateway.mcp_proxy

Env: PTGATEWAY_URL (default http://127.0.0.1:7532)
"""

from __future__ import annotations

import asyncio
import json
import os

import httpx
import mcp.types as T
from mcp.server import Server
from mcp.server.stdio import stdio_server

from .legacy_schemas import TOOLS as LEGACY
from .tools import COMPOSITE_SCHEMAS

BASE = os.environ.get("PTGATEWAY_URL", "http://127.0.0.1:7532")


def descriptors() -> list[T.Tool]:
    out = [T.Tool(name=t["name"], description=t["description"], inputSchema=t["inputSchema"]) for t in LEGACY]
    for name, s in COMPOSITE_SCHEMAS.items():
        out.append(T.Tool(name=name, description=s["description"],
                          inputSchema={"type": "object", "properties": s["properties"], "required": s["required"]}))
    return out


def build() -> Server:
    app: Server = Server("packet-tracer")
    tools = descriptors()

    @app.list_tools()
    async def _list() -> list[T.Tool]:
        return tools

    @app.call_tool()
    async def _call(name: str, arguments: dict) -> list[T.TextContent]:
        async with httpx.AsyncClient(timeout=600) as c:
            try:
                r = await c.post(f"{BASE}/api/pt/tool/{name}", json=arguments or {})
                data = r.json()
            except httpx.HTTPError as exc:
                data = {"success": False,
                        "error": f"ptgateway not reachable at {BASE}: {exc}. Start it: python -m ptgateway"}
        return [T.TextContent(type="text", text=json.dumps(data, indent=1, default=str))]

    return app


async def run() -> None:
    app = build()
    async with stdio_server() as (r, w):
        await app.run(r, w, app.create_initialization_options())


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
