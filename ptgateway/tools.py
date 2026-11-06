"""Packet Tracer tools for the ptgateway (cisco-pt-mcp-plus).

Two kinds of tools:

* LEGACY tools are forwarded unchanged to the cisco-pt-mcp plugin functions
  (addDevice, configureIosDevice, sendPdu, ...).
* COMPOSITE tools are implemented here as short JavaScript snippets that run
  inside PT's script engine through the plugin's ``ptEval`` hook (added by our
  patched module in plugin/). They cover everything the
  stock plugin cannot do: server services, DHCP pools, DNS records, web pages,
  PC command-prompt output (ping/telnet/ssh/ipconfig), IOS ``show`` output and
  an HTTP client on end devices.

PT API names come from the Cisco Packet Tracer Extensions API reference
(tutorials.ptnetacad.net/help/default/IpcAPI). Where the process name passed to
``Device.getProcess`` is not documented we try a short list of candidates and
report which one worked (see ``probeProcesses``).
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import time
from typing import Any, Awaitable, Callable

from .bridge import PTBridge

J = json.dumps  # JSON literals are valid JS literals

PRELUDE = r"""
var dev = ipc.network().getDevice(%(dev)s);
if (!dev) { throw new Error("device not found: " + %(dev)s); }
function S(x) { try { return (x === null || x === undefined) ? null : String(x); } catch (e) { return null; } }
function proc(names) {
  for (var i = 0; i < names.length; i++) {
    try { var p = dev.getProcess(names[i]); if (p) { return { p: p, name: names[i] }; } } catch (e) {}
  }
  return null;
}
function termLine() {
  var c = [];
  try { c.push(dev.getCommandLine()); } catch (e) {}
  try { c.push(dev.getCommandPrompt()); } catch (e) {}
  for (var i = 0; i < c.length; i++) { if (c[i] && typeof c[i].getOutput === "function") { return c[i]; } }
  if (c.length && c[0]) { return c[0]; }
  throw new Error("no terminal line on " + %(dev)s);
}
"""

SERVICE_PROCS = {
    "http": ["HttpServer"],
    "https": ["HttpsServer"],
    "dns": ["DnsServer", "DnsServerProcess"],
    "dhcp": ["DhcpServerMainProcess", "DhcpServerMain", "DhcpServer"],
    "syslog": ["SyslogServer", "SyslogServerProcess"],
    "ntp": ["NtpServer", "NtpServerProcess"],
    "iot": ["IoEServer", "IoeServer", "IoEServerProcess", "IoeServerProcess"],
    "ftp": ["FtpServer"],
    "tftp": ["TftpServer"],
    "email": ["EmailServer", "SmtpServer"],
    "httpclient": ["HttpClient", "HttpBackgroundClient"],
    "dhcpclient": ["DhcpClient"],
}

LEGACY_TOOLS = [
    "addDevice", "addModule", "addLink", "removeDevice", "removeLink", "configurePcIp",
    "configureIosDevice", "getNetwork", "getDeviceInfo", "setSimulationMode",
    "getSimulationStatus", "stepSimulation", "sendPdu", "renameDevice", "moveDevice",
    "setPower", "getPduResults", "getCommandLog",
]


def _js(dev: str, body: str) -> str:
    return PRELUDE % {"dev": J(dev)} + body


def _dhcp_js() -> str:
    names = J(SERVICE_PROCS["dhcp"])
    return (
        "var pr = proc(" + names + ");\n"
        'if (!pr) { throw new Error("no DHCP server process"); }\n'
        "var dhcp = pr.p;\n"
        'if (typeof dhcp.getDhcpServerProcessByPortName === "function") {\n'
        '  dhcp = dhcp.getDhcpServerProcessByPortName("FastEthernet0");\n'
        "}\n"
        "function poolInfo(p) { return { name: S(p.getDhcpPoolName()), network: S(p.getNetworkAddress()),\n"
        "  mask: S(p.getSubnetMask()), gateway: S(p.getDefaultRouter()), dns: S(p.getDnsServerIp()),\n"
        "  start: S(p.getStartIp()), end: S(p.getEndIp()), max: p.getMaxUsers() }; }\n"
        "function pools() { var out = []; for (var i = 0; i < dhcp.getPoolCount(); i++) { out.push(poolInfo(dhcp.getPoolAt(i))); } return out; }\n"
    )


class PTTools:
    """All tools exposed by the gateway (REST, MCP proxy, live runner)."""

    def __init__(self, bridge: PTBridge) -> None:
        self.bridge = bridge
        self.composite: dict[str, Callable[..., Awaitable[dict]]] = {
            "ptEval": self.pt_eval,
            "probeProcesses": self.probe_processes,
            "setServerService": self.set_server_service,
            "listDhcpPools": self.list_dhcp_pools,
            "setDhcpPool": self.set_dhcp_pool,
            "removeDhcpPool": self.remove_dhcp_pool,
            "addDnsRecord": self.add_dns_record,
            "listDnsRecords": self.list_dns_records,
            "setHttpPage": self.set_http_page,
            "getHostIp": self.get_host_ip,
            "renewDhcp": self.renew_dhcp,
            "pcCommand": self.pc_command,
            "pcSession": self.pc_session,
            "iosExec": self.ios_exec,
            "httpGet": self.http_get,
            "listDevices": self.list_devices,
        }

    # ------------------------------------------------------------- dispatch
    def names(self) -> list[str]:
        return LEGACY_TOOLS + list(self.composite)

    async def call(self, name: str, args: dict[str, Any] | None = None) -> dict:
        args = dict(args or {})
        if name in self.composite:
            try:
                return await self.composite[name](**args)
            except TypeError as exc:
                return {"success": False, "error": f"bad arguments for {name}: {exc}"}
            except Exception as exc:  # noqa: BLE001
                return {"success": False, "error": str(exc)}
        if name in LEGACY_TOOLS:
            try:
                return await self.bridge.call(name, args)
            except Exception as exc:  # noqa: BLE001
                return {"success": False, "error": str(exc)}
        return {"success": False, "error": f"unknown tool {name}"}

    async def _eval(self, code: str) -> Any:
        res = await self.bridge.call("ptEval", {"code": code})
        if not isinstance(res, dict) or res.get("success") is False:
            err = (res or {}).get("error") if isinstance(res, dict) else res
            if isinstance(err, str) and "unsupported tool" in err:
                raise RuntimeError("PT module is the stock cisco-pt-mcp build (no ptEval). "
                                   "Install the patched module: docs/INSTALL-PLUGIN.md")
            raise RuntimeError(f"PT script error: {err}")
        out = res.get("result")
        # The patched module's ptEval returns {success, result}; the webview wraps
        # that once more, so unwrap the inner envelope as well.
        if isinstance(out, dict) and "success" in out and set(out) <= {"success", "result", "error"}:
            if out.get("success") is False:
                raise RuntimeError(f"PT script error: {out.get('error')}")
            out = out.get("result")
        return out

    # ------------------------------------------------------------ composite
    async def pt_eval(self, code: str) -> dict:
        return {"success": True, "result": await self._eval(code)}

    async def probe_processes(self, deviceName: str, names: list[str] | None = None) -> dict:
        names = names or sorted({n for v in SERVICE_PROCS.values() for n in v})
        body = (
            "var out = {};\n"
            "var names = " + J(names) + ";\n"
            "for (var i = 0; i < names.length; i++) { var ok = false;\n"
            "  try { ok = !!dev.getProcess(names[i]); } catch (e) { ok = false; }\n"
            "  out[names[i]] = ok; }\n"
            "return out;"
        )
        return {"success": True, "result": await self._eval(_js(deviceName, body))}

    async def set_server_service(self, deviceName: str, service: str, enabled: bool = True) -> dict:
        service = service.lower()
        if service not in SERVICE_PROCS:
            return {"success": False, "error": f"service must be one of {sorted(SERVICE_PROCS)}"}
        if service == "dhcp":
            body = _dhcp_js() + f"dhcp.setEnable({J(bool(enabled))});\nreturn {{ process: pr.name, enabled: {J(bool(enabled))} }};"
        else:
            # Never call isEnabled() after setEnable(false): it crashes PT on HttpServer.
            body = (
                "var pr = proc(" + J(SERVICE_PROCS[service]) + ");\n"
                'if (!pr) { throw new Error("no process for ' + service + '"); }\n'
                # NtpServer exposes setEnabled(); the IoE server exposes neither.
                f"if (typeof pr.p.setEnable === 'function') {{ pr.p.setEnable({J(bool(enabled))}); }}\n"
                f"else if (typeof pr.p.setEnabled === 'function') {{ pr.p.setEnabled({J(bool(enabled))}); }}\n"
                "else { throw new Error('no on/off method on ' + pr.name + ' (set it in the Services tab)'); }\n"
                f"return {{ process: pr.name, enabled: {J(bool(enabled))} }};"
            )
        return {"success": True, "result": await self._eval(_js(deviceName, body))}

    async def list_dhcp_pools(self, deviceName: str) -> dict:
        body = _dhcp_js() + "return { enabled: !!dhcp.isEnable(), pools: pools() };"
        return {"success": True, "result": await self._eval(_js(deviceName, body))}

    async def set_dhcp_pool(self, deviceName: str, poolName: str, gateway: str, dns: str,
                            startIp: str, mask: str, maxUsers: int) -> dict:
        net = ipaddress.IPv4Network(f"{startIp}/{mask}", strict=False)
        end = str(ipaddress.IPv4Address(startIp) + int(maxUsers) - 1)
        body = _dhcp_js() + (
            f"var name = {J(poolName)};\n"
            "var p = null; try { p = dhcp.getPool(name); } catch (e) { p = null; }\n"
            "var how = 'updated';\n"
            "if (!p) {\n"
            f"  dhcp.addNewPool(name, {J(gateway)}, {J(dns)}, {J(startIp)}, {J(mask)}, {int(maxUsers)}, '0.0.0.0', '0.0.0.0');\n"
            "  how = 'created';\n"
            "} else {\n"
            f"  p.setNetworkMask({J(str(net.network_address))}, {J(mask)});\n"
            f"  p.setDefaultRouter({J(gateway)}); p.setDnsServerIp({J(dns)});\n"
            f"  p.setStartIp({J(startIp)}); p.setEndIp({J(end)}); p.setMaxUsers({int(maxUsers)});\n"
            "}\n"
            "dhcp.setEnable(true);\n"
            "return { action: how, pools: pools() };"
        )
        return {"success": True, "result": await self._eval(_js(deviceName, body))}

    async def remove_dhcp_pool(self, deviceName: str, poolName: str) -> dict:
        body = _dhcp_js() + f"dhcp.removePool({J(poolName)});\nreturn {{ pools: pools() }};"
        return {"success": True, "result": await self._eval(_js(deviceName, body))}

    async def add_dns_record(self, deviceName: str, name: str, ip: str) -> dict:
        body = (
            "var pr = proc(" + J(SERVICE_PROCS["dns"]) + ");\n"
            'if (!pr) { throw new Error("no DNS server process"); }\n'
            "var dns = pr.p; dns.setEnable(true);\n"
            "var r = { a: null, entry: null };\n"
            f"try {{ r.a = !!dns.addARecordToNameServerDb({J(name)}, {J(ip)}); }} catch (e) {{ r.a = 'err: ' + e; }}\n"
            f"try {{ r.entry = !!dns.addIpAddress({J(name)}, {J(ip)}); }} catch (e) {{ r.entry = 'err: ' + e; }}\n"
            "r.records = dns.getSizeOfNameServerDb();\n"
            "return r;"
        )
        return {"success": True, "result": await self._eval(_js(deviceName, body))}

    async def list_dns_records(self, deviceName: str) -> dict:
        body = (
            "var pr = proc(" + J(SERVICE_PROCS["dns"]) + ");\n"
            'if (!pr) { throw new Error("no DNS server process"); }\n'
            "var dns = pr.p; var out = [];\n"
            "for (var i = 0; i < dns.getEntryCount(); i++) { var e = dns.getEntryAt(i);\n"
            "  try { out.push({ name: S(e.first || e[0]), ip: S(e.second || e[1]) }); } catch (x) { out.push(S(e)); } }\n"
            "return { enabled: !!dns.isEnabled(), entries: out, dbSize: dns.getSizeOfNameServerDb() };"
        )
        return {"success": True, "result": await self._eval(_js(deviceName, body))}

    async def set_http_page(self, deviceName: str, content: str, path: str = "index.html",
                            https: bool = True) -> dict:
        body = (
            "var h = proc(['HttpServer']);\n"
            'if (!h) { throw new Error("no HttpServer"); }\n'
            f"h.p.setEnable(true); h.p.setPageContents({J(path)}, {J(content)});\n"
            "var hs = null;\n"
            f"if ({J(bool(https))}) {{ hs = proc(['HttpsServer']); if (hs) {{ hs.p.setEnable(true); }} }}\n"
            f"return {{ page: S(h.p.getPage({J(path)})), https: !!hs }};"
        )
        return {"success": True, "result": await self._eval(_js(deviceName, body))}

    async def get_host_ip(self, deviceName: str, port: str = "FastEthernet0") -> dict:
        body = (
            f"var p = dev.getPort({J(port)});\n"
            f'if (!p) {{ throw new Error("no port " + {J(port)}); }}\n'
            "var r = { ip: S(p.getIpAddress()), mask: S(p.getSubnetMask()), mac: null, dhcp: null, gateway: null };\n"
            "try { r.mac = S(p.getMacAddress()); } catch (e) {}\n"
            "try { r.dhcp = !!p.isDhcpClientOn(); } catch (e) {}\n"
            "try { r.gateway = S(p.getDefaultGateway()); } catch (e) {}\n"
            "return r;"
        )
        return {"success": True, "result": await self._eval(_js(deviceName, body))}

    async def renew_dhcp(self, deviceName: str, port: str = "FastEthernet0", wait: float = 6.0) -> dict:
        body = (
            f"var p = dev.getPort({J(port)});\n"
            "p.setDhcpClientFlag(true);\n"
            "var c = proc(['DhcpClient']);\n"
            f"if (c && typeof c.p.dhcpRun === 'function') {{ c.p.dhcpRun({J(port)}); }}\n"
            "return { started: true, viaProcess: !!c };"
        )
        await self._eval(_js(deviceName, body))
        deadline = time.time() + wait
        ip = None
        while time.time() < deadline:
            await asyncio.sleep(1.0)
            ip = (await self.get_host_ip(deviceName, port))["result"]
            if ip.get("ip") and ip["ip"] not in ("0.0.0.0", "None") and not ip["ip"].startswith("169.254"):
                break
        return {"success": True, "result": ip}

    async def _term_read(self, dev: str, start: int) -> dict:
        body = (
            "var line = termLine(); var out = S(line.getOutput()) || '';\n"
            f"var from = {int(start)}; if (out.length < from) {{ from = 0; }}\n"
            "var pr = null; try { pr = S(line.getPrompt()); } catch (e) {}\n"
            "return { len: out.length, text: out.substring(from), prompt: pr };"
        )
        return await self._eval(_js(dev, body))

    async def _term_send(self, dev: str, line_text: str, ios_mode: str | None = None) -> int:
        if ios_mode is not None:
            send = f"dev.enterCommand({J(line_text)}, {J(ios_mode)});"
        else:
            send = f"line.enterCommand({J(line_text)});"
        body = (
            "var line = termLine(); var before = (S(line.getOutput()) || '').length;\n"
            + send + "\nreturn before;"
        )
        return int(await self._eval(_js(dev, body)) or 0)

    async def _collect(self, dev: str, start: int, wait: float, settle: float,
                       done: re.Pattern | None) -> dict:
        t0 = time.time()
        last_len, last_change, snap = -1, time.time(), {"text": "", "prompt": None}
        while True:
            await asyncio.sleep(0.6)
            snap = await self._term_read(dev, start)
            now = time.time()
            if snap["len"] != last_len:
                last_len, last_change = snap["len"], now
            text = snap.get("text") or ""
            if done is not None and done.search(text) and now - last_change >= 0.8:
                break
            if text and now - last_change >= settle:
                break
            if now - t0 >= wait:
                snap["timedOut"] = True
                break
        snap["elapsed_s"] = round(time.time() - t0, 1)
        return snap

    async def pc_command(self, deviceName: str, command: str, wait: float = 30.0,
                         settle: float = 6.0) -> dict:
        """Type a command into an end device's Command Prompt and return the output.

        PT must be in realtime mode. ``ping`` finishes with a statistics block,
        ``telnet``/``ssh`` with a login prompt or a timeout message.
        """
        start = await self._term_send(deviceName, command)
        done = re.compile(r"(Ping statistics[\s\S]*?(Minimum|Lost = \d+ \(\d+% loss\)))|"
                          r"Password:|Username:|timed out|refused|Unknown|Invalid|C:\\>\s*$", re.I)
        snap = await self._collect(deviceName, start, wait, settle, done)
        return {"success": True, "result": {"command": command, "output": snap.get("text", ""),
                                            "prompt": snap.get("prompt"), "timedOut": snap.get("timedOut", False),
                                            "elapsed_s": snap["elapsed_s"]}}

    async def pc_session(self, deviceName: str, lines: list[str], wait: float = 20.0) -> dict:
        """Send several lines (e.g. telnet + password + exit), output after each."""
        out = []
        for ln in lines:
            start = await self._term_send(deviceName, ln)
            snap = await self._collect(deviceName, start, wait, 3.0, None)
            out.append({"line": ln if "pass" not in ln.lower() else "***", "output": snap.get("text", "")})
        return {"success": True, "result": out}

    async def ios_exec(self, deviceName: str, command: str, wait: float = 15.0) -> dict:
        """Run an exec-mode IOS command (show ...) and capture the console output."""
        # PT 9: Device.enterCommand returns {first: code, second: output} without
        # echoing to the console line, so use the return value when present.
        direct = await self._eval(_js(deviceName,
            f"var x = dev.enterCommand({J(command)}, 'enable');\n"
            "if (x && x.second !== undefined) { return { output: S(x.second) }; }\n"
            "return { output: null };"))
        if isinstance(direct, dict) and direct.get("output") is not None:
            return {"success": True, "result": {"command": command, "output": direct["output"],
                                                "prompt": None}}
        await self._term_send(deviceName, "terminal length 0", ios_mode="enable")
        start = await self._term_send(deviceName, command, ios_mode="enable")
        snap = await self._collect(deviceName, start, wait, 2.5, re.compile(r"[#>]\s*$"))
        return {"success": True, "result": {"command": command, "output": snap.get("text", ""),
                                            "prompt": snap.get("prompt")}}

    async def http_get(self, deviceName: str, url: str, wait: float = 20.0, https: bool = False) -> dict:
        """Browse ``url`` from an end device (PT HttpClient) and return the page text.

        Returns the last page content once it changes from what it was before
        the request; ``changed`` false + timeout means no response.
        """
        names = J(SERVICE_PROCS["httpclient"])
        body_start = (
            "var c = proc(" + names + ");\n"
            'if (!c) { throw new Error("no HttpClient process"); }\n'
            "var before = S(c.p.getLastPageContent()) || '';\n"
            f"try {{ c.p.setHttps({J(bool(https))}); }} catch (e) {{}}\n"
            f"var ok = c.p.go({J(url)});\n"
            "return { process: c.name, before: before, accepted: !!ok };"
        )
        st = await self._eval(_js(deviceName, body_start))
        before = st.get("before", "")
        body_read = "var c = proc(" + names + ");\nreturn S(c.p.getLastPageContent()) || '';"
        t0, page = time.time(), before
        while time.time() - t0 < wait:
            await asyncio.sleep(1.0)
            page = await self._eval(_js(deviceName, body_read))
            if page != before:
                break
        return {"success": True, "result": {"url": url, "accepted": st.get("accepted"),
                                            "changed": page != before, "content": page[:4000],
                                            "elapsed_s": round(time.time() - t0, 1)}}

    async def list_devices(self) -> dict:
        body = (
            "var net = ipc.network(); var out = [];\n"
            "for (var i = 0; i < net.getDeviceCount(); i++) { var d = net.getDeviceAt(i);\n"
            "  var r = { name: S(d.getName()), model: S(d.getModel()), type: d.getType(), x: null, y: null, ip: null, power: null };\n"
            "  try { r.x = d.getXCoordinate(); r.y = d.getYCoordinate(); } catch (e) {}\n"
            "  try { r.power = !!d.getPower(); } catch (e) {}\n"
            "  try { var p = d.getPort('FastEthernet0'); if (p && p.getIpAddress) { r.ip = S(p.getIpAddress()); } } catch (e) {}\n"
            "  out.push(r); }\n"
            "return out;"
        )
        code = "function S(x){try{return (x===null||x===undefined)?null:String(x);}catch(e){return null;}}\n" + body
        return {"success": True, "result": await self._eval(code)}


# JSON schemas for the MCP proxy (composite tools only; legacy schemas are
# copied from cisco-pt-mcp at runtime).
COMPOSITE_SCHEMAS: dict[str, dict] = {
    "ptEval": {"description": "Run a JavaScript function body inside Packet Tracer's script engine (must return JSON-serialisable data). Expert escape hatch.",
               "properties": {"code": {"type": "string"}}, "required": ["code"]},
    "probeProcesses": {"description": "Report which Device.getProcess names exist on a device (debug).",
                       "properties": {"deviceName": {"type": "string"}, "names": {"type": "array", "items": {"type": "string"}}},
                       "required": ["deviceName"]},
    "setServerService": {"description": "Turn a Server-PT service on/off: http, https, dns, dhcp, syslog, ntp, iot, ftp, tftp, email.",
                         "properties": {"deviceName": {"type": "string"}, "service": {"type": "string"}, "enabled": {"type": "boolean"}},
                         "required": ["deviceName", "service"]},
    "listDhcpPools": {"description": "List DHCP pools on a Server-PT.", "properties": {"deviceName": {"type": "string"}}, "required": ["deviceName"]},
    "setDhcpPool": {"description": "Create or update a DHCP pool on a Server-PT (serverPool can only be updated).",
                    "properties": {"deviceName": {"type": "string"}, "poolName": {"type": "string"}, "gateway": {"type": "string"},
                                   "dns": {"type": "string"}, "startIp": {"type": "string"}, "mask": {"type": "string"},
                                   "maxUsers": {"type": "integer"}},
                    "required": ["deviceName", "poolName", "gateway", "dns", "startIp", "mask", "maxUsers"]},
    "removeDhcpPool": {"description": "Remove a DHCP pool.", "properties": {"deviceName": {"type": "string"}, "poolName": {"type": "string"}},
                       "required": ["deviceName", "poolName"]},
    "addDnsRecord": {"description": "Enable DNS on a Server-PT and add an A record.",
                     "properties": {"deviceName": {"type": "string"}, "name": {"type": "string"}, "ip": {"type": "string"}},
                     "required": ["deviceName", "name", "ip"]},
    "listDnsRecords": {"description": "List DNS entries on a Server-PT.", "properties": {"deviceName": {"type": "string"}}, "required": ["deviceName"]},
    "setHttpPage": {"description": "Enable HTTP(+HTTPS) on a Server-PT and set a page's HTML.",
                    "properties": {"deviceName": {"type": "string"}, "content": {"type": "string"}, "path": {"type": "string"},
                                   "https": {"type": "boolean"}}, "required": ["deviceName", "content"]},
    "getHostIp": {"description": "Read IP/mask/MAC/DHCP flag of an end-device port.",
                  "properties": {"deviceName": {"type": "string"}, "port": {"type": "string"}}, "required": ["deviceName"]},
    "renewDhcp": {"description": "Switch an end device to DHCP, request a lease and return the address.",
                  "properties": {"deviceName": {"type": "string"}, "port": {"type": "string"}, "wait": {"type": "number"}},
                  "required": ["deviceName"]},
    "pcCommand": {"description": "Type a command into a PC/laptop/server Command Prompt (ping, ipconfig, telnet, ssh, nslookup, tracert) and return its output. Realtime mode.",
                  "properties": {"deviceName": {"type": "string"}, "command": {"type": "string"}, "wait": {"type": "number"},
                                 "settle": {"type": "number"}}, "required": ["deviceName", "command"]},
    "pcSession": {"description": "Send several lines to an end-device prompt in order (e.g. telnet, password, exit).",
                  "properties": {"deviceName": {"type": "string"}, "lines": {"type": "array", "items": {"type": "string"}},
                                 "wait": {"type": "number"}}, "required": ["deviceName", "lines"]},
    "iosExec": {"description": "Run an exec-mode IOS command (e.g. show access-lists) on a router/switch and return console output.",
                "properties": {"deviceName": {"type": "string"}, "command": {"type": "string"}, "wait": {"type": "number"}},
                "required": ["deviceName", "command"]},
    "httpGet": {"description": "Open a URL in an end device's web browser (PT HttpClient) and return page content.",
                "properties": {"deviceName": {"type": "string"}, "url": {"type": "string"}, "wait": {"type": "number"},
                               "https": {"type": "boolean"}}, "required": ["deviceName", "url"]},
    "listDevices": {"description": "List every device with model, type, canvas position, power and Fa0 IP.", "properties": {}, "required": []},
}
