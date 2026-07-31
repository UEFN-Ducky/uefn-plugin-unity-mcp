---
name: unity-mcp
description: >-
  Control Unity Editor through the UNITY MCP Store plugin (Coplay). Call
  unity_list_tools to see what the open Unity project exposes, then unity_call
  to run one. Zero-setup: install plugin, open a Unity Hub project — no Package
  Manager or URL steps. Use when the user mentions Unity, GameObjects, prefabs,
  or Unity MCP.
license: All Rights Reserved
metadata:
  label: UNITY MCP
  version: 3
  author: UEFN-Ducky
  copyright: Copyright 2026 UEFN-Ducky
  allow_redistribute: false
  managed_by: uefn-ducky
  source_plugin_id: unity-mcp
---

# UNITY MCP — Coplay Unity Editor bridge

You control **Unity Editor** through the **UNITY MCP** Store plugin. The plugin
runs Coplay’s [MCP for Unity](https://github.com/CoplayDev/unity-mcp) server
locally and forwards calls for you — Unity tools are reached through
`unity_list_tools` + `unity_call`, not as separate `unity__*` entries.

**Unity work does NOT need the UEFN / Fortnite listener.** If UNITY MCP is
ready, proceed. Do not wait for UEFN.

**Do not mix stacks:** UEFN/Verse/island tools are for Fortnite. Use the
`unity_*` tools only for Unity projects.

## Zero-setup (user)

1. Install / enable Store plugin **UNITY MCP** (`unity-mcp`).
2. Open a Unity project from **Unity Hub**.

That’s it. The plugin:

- runs the local Coplay HTTP server on `http://127.0.0.1:8080/mcp`
- injects the MCP for Unity package into each **open** Hub project
- configures auto-start so the Editor connects without Window → MCP for Unity

## Calling Unity

1. `unity_list_tools` — returns the live tool names, descriptions, and input
   schemas from the connected project. Never guess a tool name; the set depends
   on the installed Coplay version.
2. `unity_call(tool="<name>", arguments={...})` — arguments must match that
   tool’s input schema. A JSON object string is accepted too.

## Status tool

Call `unity_status` when connectivity is unclear. `state` values:

| state | Meaning |
|-------|---------|
| `downloading` | Fetching managed `uv` |
| `starting` | Starting local HTTP server |
| `waiting_for_unity` | No open Hub project yet — tell user to open Unity |
| `importing` | Injecting package / bootstrap into open project(s) |
| `connecting` | Server up; waiting for Editor bridge |
| `ready` | Use `unity_list_tools` then `unity_call` |
| `error` | See `error` fields; `unity_redeploy` after fix |

## Hard rules

- Never invent Unity scene state — query it with `unity_call` first.
- Never use UEFN `spawn_actor` / Verse tools for Unity work.
- If status is `waiting_for_unity`, ask the user to open a Unity Hub project —
  do not send Package Manager git-URL instructions.
- If `unity_status` shows unreachable / error, call `unity_redeploy` or fix the
  reported error — do not retry UEFN tools as a substitute.
