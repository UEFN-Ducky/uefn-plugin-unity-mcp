"""UNITY MCP — Store desktop plugin; zero-setup Coplay Unity bridge."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from .constants import DEFAULT_URL, PLUGIN_ID, UNITY_INTENT

log = logging.getLogger("uefn.plugin.unity-mcp")

_RUNTIME_THREAD: threading.Thread | None = None
_STOP = threading.Event()


def register(api: Any) -> None:
    """Start the managed server + project watcher and register the Unity tools."""
    from . import legacy

    cleanup = legacy.remove_legacy_nested_server()
    if cleanup.get("removed"):
        api.log("UNITY MCP removed the old nested mcp.json row — tools are plugin-owned now")

    if api.is_enabled():
        _start_runtime_async(api.log)

    @api.tool(name="unity_status", intent=UNITY_INTENT, listener=False)
    def unity_status() -> str:
        """Report UNITY MCP readiness: server, open Unity projects, live tool count."""
        return json.dumps(_build_status(), indent=2)

    @api.tool(name="unity_list_tools", intent=UNITY_INTENT, listener=False)
    def unity_list_tools() -> str:
        """List the Unity Editor tools the connected project exposes, with input schemas."""
        from . import client

        try:
            tools = client.list_tools()
        except Exception as exc:
            return json.dumps(
                {"ok": False, "error": str(exc), "status": _build_status()},
                indent=2,
            )
        return json.dumps({"ok": True, "count": len(tools), "tools": tools}, indent=2)

    @api.tool(name="unity_call", intent=UNITY_INTENT, listener=False)
    def unity_call(tool: str, arguments: dict[str, Any] | None = None) -> str:
        """Call one Unity Editor tool by name (see unity_list_tools) with its arguments."""
        from . import client

        name = (tool or "").strip()
        if not name:
            return json.dumps({"ok": False, "error": "tool name is required"}, indent=2)
        try:
            args = _coerce_arguments(arguments)
        except ValueError as exc:
            return json.dumps({"ok": False, "error": str(exc)}, indent=2)
        try:
            return json.dumps(client.call_tool(name, args), indent=2, default=str)
        except Exception as exc:
            return json.dumps(
                {"ok": False, "tool": name, "error": str(exc), "status": _build_status()},
                indent=2,
            )

    @api.tool(name="unity_redeploy", intent=UNITY_INTENT, listener=False)
    def unity_redeploy() -> str:
        """Re-run zero-setup: ensure the server and re-inject MCP for Unity into open projects."""
        from . import projects, runtime

        uv = runtime.ensure_uv()
        server = runtime.ensure_server()
        sync = projects.sync_open_projects()
        return json.dumps(
            {
                "ok": bool(uv.get("ok") and server.get("ok")),
                "uv": uv,
                "server": server,
                "projects": sync,
                "status": _build_status(),
            },
            indent=2,
        )

    api.log("UNITY MCP tools registered")


def unload() -> None:
    """Stop the watcher and the plugin-owned server."""
    _stop_runtime()


def _coerce_arguments(arguments: Any) -> dict[str, Any]:
    """Accept a mapping or a JSON object string — models send both."""
    if arguments is None or arguments == "":
        return {}
    if isinstance(arguments, dict):
        return dict(arguments)
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise ValueError(f"arguments is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("arguments must be a JSON object")
        return parsed
    raise ValueError("arguments must be an object")


def _start_runtime_async(log_fn: Any) -> None:
    global _RUNTIME_THREAD
    _STOP.clear()

    def _run() -> None:
        from . import projects, runtime

        try:
            log_fn("UNITY MCP zero-setup starting")
        except Exception:
            pass
        try:
            uv = runtime.ensure_uv()
            if not uv.get("ok"):
                runtime.set_phase("error", error=str(uv.get("error") or "uv failed"))
                try:
                    log_fn(f"UNITY MCP uv failed: {uv.get('error')}")
                except Exception:
                    pass
                return
            server = runtime.ensure_server()
            try:
                log_fn(
                    f"UNITY MCP server: ok={server.get('ok')} "
                    f"reused={server.get('reused')} started={server.get('started')}"
                )
            except Exception:
                pass
            projects.start_watcher(log_fn)
            # Keep nudging the server until reachable or stop requested.
            while not _STOP.is_set():
                try:
                    runtime.ensure_server()
                except Exception as exc:
                    log.warning("server ensure failed: %s", exc)
                if _STOP.wait(8.0):
                    break
        except Exception as exc:
            log.warning("unity runtime failed: %s", exc)
            try:
                log_fn(f"UNITY MCP runtime failed: {exc}")
            except Exception:
                pass

    thread = threading.Thread(
        target=_run,
        daemon=True,
        name="unity-mcp-runtime",
    )
    _RUNTIME_THREAD = thread
    thread.start()


def _stop_runtime() -> None:
    global _RUNTIME_THREAD
    _STOP.set()
    try:
        from . import projects

        projects.stop_watcher()
    except Exception:
        pass
    try:
        from . import runtime

        runtime.stop_server()
    except Exception:
        pass
    thread = _RUNTIME_THREAD
    _RUNTIME_THREAD = None
    if thread and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=2.0)


def _tools_status(reachable: bool) -> dict[str, Any]:
    """Live tool list — only probed once the HTTP endpoint answers."""
    if not reachable:
        return {"available": False, "reason": "server unreachable"}
    from . import client

    try:
        tools = client.list_tools()
    except Exception as exc:
        return {"available": False, "error": str(exc)}
    return {
        "available": True,
        "count": len(tools),
        "names": [str(t.get("name") or "") for t in tools],
    }


def _build_status() -> dict[str, Any]:
    from . import projects, runtime

    rt = runtime.runtime_status()
    proj = projects.projects_status()
    probe_ok = bool((rt.get("probe") or {}).get("reachable"))
    tools = _tools_status(probe_ok)
    has_open = bool(proj.get("open_projects"))
    configured = bool(proj.get("configured"))

    if rt.get("phase") == "downloading":
        overall = "downloading"
    elif rt.get("phase") == "error" or proj.get("phase") == "error":
        overall = "error"
    elif not probe_ok and rt.get("phase") in ("starting", "downloading"):
        overall = "starting"
    elif not has_open:
        overall = "waiting_for_unity"
    elif has_open and not configured:
        overall = "importing"
    elif probe_ok and configured:
        overall = "ready"
    else:
        overall = "connecting"

    hint = {
        "downloading": "Downloading managed uv for the Coplay MCP server…",
        "starting": "Starting the local Unity MCP HTTP server…",
        "waiting_for_unity": "Open a Unity project from Unity Hub — package install is automatic.",
        "importing": "Injecting MCP for Unity into open project(s)…",
        "connecting": "Waiting for Unity Editor to connect to the local MCP server…",
        "ready": "Ready. Call unity_list_tools, then unity_call.",
        "error": "See error fields; call unity_redeploy after fixing the issue.",
    }.get(overall, "")

    return {
        "ok": overall == "ready",
        "plugin_id": PLUGIN_ID,
        "state": overall,
        "hint": hint,
        "url": DEFAULT_URL,
        "runtime": rt,
        "projects": proj,
        "tools": tools,
    }
