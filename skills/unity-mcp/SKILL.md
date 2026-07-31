---
name: unity-mcp
description: >-
  Control Unity Editor through the UNITY MCP Store plugin (Coplay). Nested
  tools appear as unity__* on uefn-ducky. Zero-setup: install plugin, open a
  Unity Hub project — no Package Manager or URL steps. Use when the user
  mentions Unity, GameObjects, prefabs, or Unity MCP.
license: All Rights Reserved
metadata:
  label: UNITY MCP
  version: 2
  author: UEFN-Ducky
  copyright: Copyright 2026 UEFN-Ducky
  allow_redistribute: false
  managed_by: uefn-ducky
  source_plugin_id: unity-mcp
---

# UNITY MCP — Coplay Unity Editor bridge

You control **Unity Editor** through the **UNITY MCP** Store plugin. It wires
Coplay’s [MCP for Unity](https://github.com/CoplayDev/unity-mcp) as a nested
HTTP MCP server. Tools appear as `unity__*` on the shared `uefn-ducky` MCP.

**Unity work does NOT need the UEFN / Fortnite listener.** If UNITY MCP is
ready, proceed. Do not wait for UEFN.

**Do not mix stacks:** UEFN/Verse/island tools are for Fortnite. Use `unity__*`
only for Unity projects.

## Zero-setup (user)

1. Install / enable Store plugin **UNITY MCP** (`unity-mcp`).
2. Open a Unity project from **Unity Hub**.

That’s it. The plugin:

- runs the local Coplay HTTP server on `http://127.0.0.1:8080/mcp`
- injects the MCP for Unity package into each **open** Hub project
- configures auto-start so the Editor connects without Window → MCP for Unity

## Status tool

Call `unity_mcp_status` when connectivity is unclear. `state` values:

| state | Meaning |
|-------|---------|
| `downloading` | Fetching managed `uv` |
| `starting` | Starting local HTTP server |
| `waiting_for_unity` | No open Hub project yet — tell user to open Unity |
| `importing` | Injecting package / bootstrap into open project(s) |
| `connecting` | Server up; waiting for Editor bridge |
| `ready` | Use `unity__*` tools |
| `error` | See `error` fields; `unity_mcp_redeploy` after fix |

## Nested Unity tools

After ready, Coplay tools are proxied as `unity__<tool_name>`. Discover live
names from the agent tool list. Prefer those for GameObjects, scenes, assets,
scripts, and tests inside Unity.

## Hard rules

- Never invent Unity scene state — query with `unity__*` first.
- Never use UEFN `spawn_actor` / Verse tools for Unity work.
- If status is `waiting_for_unity`, ask the user to open a Unity Hub project —
  do not send Package Manager git-URL instructions.
- If `unity_mcp_status` shows unreachable / error, call `unity_mcp_redeploy`
  or fix the reported error — do not retry UEFN tools as a substitute.
