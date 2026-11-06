# Installing the patched Packet Tracer module

The gateway needs the [cisco-pt-mcp](https://github.com/muhammadbalawal/cisco-pt-mcp) script module inside Packet Tracer with **two files replaced**:

| File in the module | Replace with | Change |
|---|---|---|
| Script Engine → `userfunctions.js` | `plugin/userfunctions.js` | adds `ptEval(code)`: runs a JS function body in PT's script engine (last 13 lines) |
| Custom Interfaces → `interface.js` | `plugin/interface/interface.js` | `MCP_URL` → `http://127.0.0.1:7532`, and `ptEval: ["code"]` added to the tool whitelist (`TOOL_ARGS`) |

Every other file is identical to upstream. They're included so you can build the module from scratch.

## Option A: patch the stock module (recommended)

1. Install the stock module once. Get `cisco-pt-mcp.pts` from the upstream repo, then **Extensions → Scripting → Configure PT Script Modules → Add**.
2. Select **cisco-pt-mcp** and click **Edit**. The *Scripting* window opens.
3. **Script Engine** tab → `userfunctions.js`: click into the code, **Ctrl+A**, then paste the full content of `plugin/userfunctions.js`.
4. **Custom Interfaces** tab → `interface.js`: replace its content with `plugin/interface/interface.js`.
5. **Info** tab → section *6. Saving* → **Save**. Optionally also use **Export** to keep a `.pts` copy.
6. **Info** tab → section *7. Testing* → **Stop**, then **Start**. The running module only picks up changes after a restart.
7. Start the gateway (`python -m ptgateway`), then in PT: **Extensions → Packet Tracer MCP**. The small window shows `connected`.

> **Gotcha:** closing the *Configure PT Script Modules* dialog does **not** save your edits. Only **Info → Save** writes the `.pts`. If PT is still connected to the old server after a restart, the save didn't happen.

## Option B: new module

**Configure PT Script Modules → New.** Add every file in `plugin/` as a Script Engine file, add `plugin/interface/index.html` and `interface.js` as Custom Interface files, and add the stock `socket.io.min.js` (not included here; take it from the upstream `.pts`). Then **Info → Save / Export**.

## Different port

Change `MCP_URL` in `interface.js` and start the gateway with `--port <n>`. The two must match.

## Check it

```bash
curl http://127.0.0.1:7532/api/pt/status          # {"connected": true, ...}
curl -X POST http://127.0.0.1:7532/api/pt/tool/listDevices -H "content-type: application/json" -d "{}"
```

`{"error": "...stock cisco-pt-mcp build (no ptEval)..."}` means PT is running the unpatched module: redo steps 3–6.
