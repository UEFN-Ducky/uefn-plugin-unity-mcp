# UNITY MCP

Zero-setup Unity Editor control for UEFN-Ducky, backed by
[Coplay MCP for Unity](https://github.com/CoplayDev/unity-mcp).

Desktop plugin for [UEFN-Ducky](https://github.com/UEFN-Ducky/UEFN-Ducky) (`unity-mcp`).
Install or update from **Settings → Store** — do not install from a zip by hand.

## User flow

1. **Settings → Store → Install** UNITY MCP (auto-enabled).
2. Open a Unity project from Unity Hub.

The plugin downloads a pinned `uv`, starts `mcpforunityserver` on
`http://127.0.0.1:8080/mcp`, injects `com.coplaydev.unity-mcp` into each
**currently open** Hub project’s `Packages/manifest.json`, and writes a small
Editor bootstrap so Coplay auto-starts. No Package Manager UI, no MCP window,
no URL form.

The plugin owns the Coplay connection in-process, like the Blender plugin, so
Unity shows up once under **Settings → MCPs → Desktop plugin tools**. It writes
no `mcp.json` entry, and uninstalling the plugin removes everything (a nested
`unity` row left by versions ≤ 1.1 is deleted on first load).

## Agent tools

| Tool | Purpose |
|------|---------|
| `unity_status` | Ready-state: downloading / waiting / importing / connecting / ready |
| `unity_list_tools` | Live Unity Editor tools with input schemas |
| `unity_call` | Call one Unity Editor tool by name with its arguments |
| `unity_redeploy` | Re-ensure server + re-inject package/bootstrap into open projects |

## Build

```bash
py scripts/build_zip.py
```

Writes `deploy/unity-mcp-1.2.0.ducky-plugin.zip` (scripts/ and deploy/ are not packed).

## Publish

```bash
py scripts/release.py --publish --changelog "v1.2.0: plugin-owned Unity tools; no nested MCP row"
```

Requires `DUCKYOS_API_KEY`. Then **Settings → Store → Install / Update** in the app.

## Tests

```bash
py -m pytest backend -q
```
