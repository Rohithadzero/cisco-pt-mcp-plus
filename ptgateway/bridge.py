"""Socket.IO bridge to the Packet Tracer plugin (cisco-pt-mcp wire protocol).

Adapted from cisco-pt-mcp 0.1.6 (MIT, Muhammad Balawal) so that the bridge can
live inside the ptgateway web server instead of an MCP stdio process. The plugin
connects as a Socket.IO client; we emit ``tool_call`` and await the matching
``tool_result``.

Differences from upstream:
* attaches to an existing aiohttp application (shared with the REST API),
* calls are serialised with a lock (PT's script engine is single-threaded and
  several clients - MCP proxy, scripts, curl - share one PT),
* keeps a small ring buffer of recent calls (GET /api/pt/status).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from collections.abc import Mapping
from typing import Any

import socketio
from aiohttp import web

log = logging.getLogger(__name__)


class PTBridge:
    def __init__(self, app: web.Application, tool_timeout: float = 90.0) -> None:
        self.tool_timeout = tool_timeout
        self._sio = socketio.AsyncServer(
            async_mode="aiohttp", cors_allowed_origins="*", logger=False, engineio_logger=False
        )
        self._sio.attach(app)
        self._sid: str | None = None
        self._connected = asyncio.Event()
        self._pending: dict[str, asyncio.Future[dict]] = {}
        self._lock = asyncio.Lock()
        self.connected_since: float | None = None
        self.history: deque[dict] = deque(maxlen=200)
        self._register()

    # ------------------------------------------------------------------ events
    def _register(self) -> None:
        sio = self._sio

        @sio.event
        async def connect(sid: str, environ: dict, auth: Any = None) -> None:
            old, self._sid = self._sid, sid
            self._connected.set()
            self.connected_since = time.time()
            log.info("PT plugin connected sid=%s", sid)
            if old and old != sid:
                try:
                    await sio.disconnect(old)
                except Exception:  # noqa: BLE001
                    pass

        @sio.event
        async def disconnect(sid: str, *args: Any) -> None:
            if self._sid == sid:
                log.info("PT plugin disconnected")
                self._sid = None
                self.connected_since = None
                self._connected.clear()
                for tcid, fut in list(self._pending.items()):
                    if not fut.done():
                        fut.set_exception(RuntimeError("PT plugin disconnected mid-call"))
                    self._pending.pop(tcid, None)

        @sio.on("tool_result")
        async def tool_result(_sid: str, data: Any) -> None:
            if not isinstance(data, Mapping):
                return
            fut = self._pending.pop(str(data.get("tool_call_id")), None)
            if fut is None or fut.done():
                return
            result = data.get("result")
            if not isinstance(result, Mapping):
                fut.set_exception(RuntimeError(f"malformed tool_result: {data!r}"[:300]))
            else:
                fut.set_result(dict(result))

    # -------------------------------------------------------------------- api
    @property
    def is_connected(self) -> bool:
        return self._sid is not None

    async def wait_connected(self, timeout: float) -> bool:
        if self.is_connected:
            return True
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def call(self, tool: str, args: dict[str, Any] | None = None) -> dict:
        """Forward one raw tool call to the plugin and return its result dict."""
        if not self.is_connected:
            raise RuntimeError(
                "Packet Tracer plugin not connected. Open PT, then Extensions -> "
                "Packet Tracer MCP (patched module pointing at 127.0.0.1:7532)."
            )
        args = args or {}
        async with self._lock:
            tcid = uuid.uuid4().hex
            fut: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
            self._pending[tcid] = fut
            t0 = time.time()
            await self._sio.emit(
                "tool_call", {"tool_call_id": tcid, "tool_name": tool, "tool_input": args}, to=self._sid
            )
            try:
                res = await asyncio.wait_for(fut, timeout=self.tool_timeout)
            except asyncio.TimeoutError as exc:
                self._pending.pop(tcid, None)
                raise RuntimeError(f"{tool} timed out after {self.tool_timeout:.0f}s") from exc
            finally:
                self.history.appendleft(
                    {"t": t0, "tool": tool, "ms": int((time.time() - t0) * 1000),
                     "args": {k: (v if len(str(v)) < 120 else str(v)[:120] + "...") for k, v in args.items()}}
                )
            return res
