"""UNITY MCP — Store desktop plugin; zero-setup Coplay Unity bridge."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from .constants import DEFAULT_URL, PLUGIN_ID

log = logging.getLogger("uefn.plugin.unity-mcp")

_RUNTIME_THREAD: threading.Thread | None = None
_STOP = threading.Event()


def register(api: Any) -> None:
    """Wire nested MCP, start managed server + project watcher, register status tool."""
    from . import bridge

    try:
        result = bridge.upsert_nested_server(DEFAULT_URL)
        api.log(f"UNITY MCP nested bridge {result.get('action')} -> {DEFAULT_URL}")
    except Exception as exc:
        api.log(f"UNITY MCP nested bridge failed: {exc}")
        log.warning("unity nested upsert failed: %s", exc)

    if api.is_enabled():
        _start_runtime_async(api.log)

    @api.tool(name="unity_mcp_status", intent=r"\b(unity|unity\s*mcp)\b")
    def unity_mcp_status() -> str:
        """Report UNITY MCP readiness: server, open projects, nested bridge, probe."""
        return json.dumps(_build_status(), indent=2)

    @api.tool(name="unity_mcp_redeploy", intent=r"\b(unity|unity\s*mcp)\b")
    def unity_mcp_redeploy() -> str:
        """Re-run zero-setup: ensure server + inject package/bootstrap into open projects."""
        from . import projects, runtime

        uv = runtime.ensure_uv()
        server = runtime.ensure_server()
        sync = projects.sync_open_projects()
        try:
            bridge.upsert_nested_server(DEFAULT_URL)
        except Exception as exc:
            return json.dumps(
                {
                    "ok": False,
                    "error": f"nested upsert failed: {exc}",
                    "uv": uv,
                    "server": server,
                    "projects": sync,
                },
                indent=2,
            )
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
    """Stop watcher and plugin-owned server; disable nested MCP entry."""
    _stop_runtime()
    try:
        from . import bridge

        bridge.disable_nested_server()
    except Exception as exc:
        log.warning("unity nested disable failed: %s", exc)


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


def _build_status() -> dict[str, Any]:
    from . import bridge, projects, runtime

    rt = runtime.runtime_status()
    proj = projects.projects_status()
    nested = bridge.nested_status()
    probe_ok = bool((rt.get("probe") or {}).get("reachable"))
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
    elif probe_ok:
        overall = "connecting"
    else:
        overall = "connecting"

    hint = {
        "downloading": "Downloading managed uv for Coplay MCP server…",
        "starting": "Starting local Unity MCP HTTP server…",
        "waiting_for_unity": "Open a Unity project from Unity Hub — package install is automatic.",
        "importing": "Injecting MCP for Unity into open project(s)…",
        "connecting": "Waiting for Unity Editor to connect to the local MCP server…",
        "ready": "Ready. Use nested tools prefixed unity__.",
        "error": "See error fields; call unity_mcp_redeploy after fixing the issue.",
    }.get(overall, "")

    return {
        "ok": overall == "ready",
        "plugin_id": PLUGIN_ID,
        "state": overall,
        "hint": hint,
        "url": DEFAULT_URL,
        "runtime": rt,
        "projects": proj,
        "nested": nested,
    }
