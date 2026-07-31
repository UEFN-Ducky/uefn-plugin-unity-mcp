"""Discover open Unity Hub projects and inject MCP for Unity (zero-setup)."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .constants import (
    BOOTSTRAP_MARKER,
    BOOTSTRAP_SCRIPT_NAME,
    DEFAULT_BASE_URL,
    UNITY_PACKAGE_GIT,
    UNITY_PACKAGE_ID,
    WATCH_INTERVAL_S,
)

log = logging.getLogger("uefn.plugin.unity-mcp.projects")

_WATCH_STOP = threading.Event()
_WATCH_THREAD: threading.Thread | None = None
_STATE_LOCK = threading.Lock()
_STATE: dict[str, Any] = {
    "phase": "idle",  # idle|waiting|importing|ready|error
    "detail": "",
    "error": "",
    "hub_projects": [],
    "open_projects": [],
    "configured": [],
    "last_results": [],
}


def hub_projects_path() -> Path | None:
    """Return Unity Hub projects-v1.json path if present."""
    candidates: list[Path] = []
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA") or ""
        if appdata:
            candidates.append(Path(appdata) / "UnityHub" / "projects-v1.json")
    elif sys.platform == "darwin":
        candidates.append(
            Path.home() / "Library" / "Application Support" / "UnityHub" / "projects-v1.json"
        )
    else:
        candidates.append(Path.home() / ".config" / "UnityHub" / "projects-v1.json")
        # Flatpak / alternate layouts
        candidates.append(
            Path.home() / ".config" / "unityhub" / "projects-v1.json"
        )
    for path in candidates:
        if path.is_file():
            return path
    return None


def parse_hub_projects(raw: str | bytes | dict[str, Any]) -> list[dict[str, Any]]:
    """Parse Unity Hub projects-v1.json into [{path, title, version}, ...]."""
    if isinstance(raw, (str, bytes)):
        data = json.loads(raw)
    else:
        data = raw
    if not isinstance(data, dict):
        return []
    entries = data.get("data")
    if not isinstance(entries, dict):
        # Some older hubs nest differently
        if isinstance(data.get("projects"), dict):
            entries = data["projects"]
        else:
            return []
    out: list[dict[str, Any]] = []
    for key, value in entries.items():
        if not isinstance(value, dict):
            continue
        path = str(value.get("path") or key or "").strip()
        if not path:
            continue
        out.append(
            {
                "path": path,
                "title": str(value.get("title") or Path(path).name),
                "version": str(value.get("version") or ""),
            }
        )
    return out


def list_hub_projects(*, hub_path: Path | None = None) -> list[dict[str, Any]]:
    path = hub_path if hub_path is not None else hub_projects_path()
    if path is None or not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("hub projects read failed: %s", exc)
        return []
    try:
        return parse_hub_projects(text)
    except json.JSONDecodeError as exc:
        log.warning("hub projects parse failed: %s", exc)
        return []


def is_unity_project(root: Path) -> bool:
    return (root / "ProjectSettings" / "ProjectVersion.txt").is_file() or (
        root / "Assets"
    ).is_dir() and (root / "ProjectSettings").is_dir()


def is_project_open(root: Path) -> bool:
    """True when Unity has a lockfile for this project (best-effort open detector)."""
    lock = root / "Temp" / "UnityLockfile"
    return lock.exists()


def list_open_hub_projects(*, hub_path: Path | None = None) -> list[dict[str, Any]]:
    open_projects: list[dict[str, Any]] = []
    for proj in list_hub_projects(hub_path=hub_path):
        root = Path(proj["path"])
        try:
            if not root.is_dir() or not is_unity_project(root):
                continue
            if not is_project_open(root):
                continue
        except OSError:
            continue
        open_projects.append({**proj, "path": str(root.resolve())})
    return open_projects


def ensure_package_in_manifest(
    manifest_path: Path,
    *,
    package_id: str = UNITY_PACKAGE_ID,
    package_ref: str = UNITY_PACKAGE_GIT,
) -> dict[str, Any]:
    """Idempotently add package_id -> package_ref to Packages/manifest.json."""
    if not manifest_path.is_file():
        return {"ok": False, "changed": False, "error": f"missing {manifest_path}"}
    try:
        text = manifest_path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "changed": False, "error": str(exc)}

    if not isinstance(data, dict):
        return {"ok": False, "changed": False, "error": "manifest root must be object"}

    deps = data.get("dependencies")
    if deps is None:
        deps = {}
        data["dependencies"] = deps
    if not isinstance(deps, dict):
        return {"ok": False, "changed": False, "error": "dependencies must be object"}

    current = deps.get(package_id)
    if current == package_ref:
        return {
            "ok": True,
            "changed": False,
            "package_id": package_id,
            "package_ref": package_ref,
            "path": str(manifest_path),
        }

    deps[package_id] = package_ref
    try:
        manifest_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        return {"ok": False, "changed": False, "error": str(exc)}
    return {
        "ok": True,
        "changed": True,
        "package_id": package_id,
        "package_ref": package_ref,
        "previous": current,
        "path": str(manifest_path),
    }


def bootstrap_script_source(*, http_url: str = DEFAULT_BASE_URL) -> str:
    """C# InitializeOnLoad script that configures Coplay prefs for zero-setup."""
    # Keep string literals simple — Unity EditorPrefs keys from Coplay v10.
    return f'''#if UNITY_EDITOR
using UnityEditor;
using UnityEngine;

namespace UefnDucky.UnityMcp
{{
    /// <summary>
    /// Auto-generated by UEFN-Ducky UNITY MCP Store plugin.
    /// Configures Coplay MCP for Unity for local HTTP + auto-start.
    /// Safe to keep; idempotent.
    /// </summary>
    [InitializeOnLoad]
    internal static class UefnDuckyUnityMcpBootstrap
    {{
        private const string SessionKey = "UefnDucky.UnityMcp.BootstrapApplied";

        static UefnDuckyUnityMcpBootstrap()
        {{
            EditorPrefs.SetBool("MCPForUnity.UseHttpTransport", true);
            EditorPrefs.SetString("MCPForUnity.HttpTransportScope", "local");
            EditorPrefs.SetString("MCPForUnity.HttpUrl", "{http_url}");
            EditorPrefs.SetBool("MCPForUnity.AutoStartOnLoad", true);
            EditorPrefs.SetBool("MCPForUnity.SetupCompleted", true);
            EditorPrefs.SetBool("MCPForUnity.SetupDismissed", true);

            if (SessionState.GetBool(SessionKey, false))
            {{
                return;
            }}
            SessionState.SetBool(SessionKey, true);

            // One deferred reload so HttpAutoStartHandler sees prefs on a fresh domain.
            EditorApplication.delayCall += () =>
            {{
                if (EditorApplication.isCompiling || EditorApplication.isUpdating)
                {{
                    return;
                }}
                AssetDatabase.Refresh();
            }};
        }}
    }}
}}
#endif
'''


def ensure_bootstrap(
    project_root: Path,
    *,
    http_url: str = DEFAULT_BASE_URL,
) -> dict[str, Any]:
    editor_dir = project_root / "Assets" / "Editor"
    script_path = editor_dir / BOOTSTRAP_SCRIPT_NAME
    marker_path = editor_dir / BOOTSTRAP_MARKER
    source = bootstrap_script_source(http_url=http_url)
    try:
        editor_dir.mkdir(parents=True, exist_ok=True)
        changed = True
        if script_path.is_file():
            existing = script_path.read_text(encoding="utf-8")
            if existing == source:
                changed = False
        if changed:
            script_path.write_text(source, encoding="utf-8")
        if not marker_path.is_file():
            marker_path.write_text(
                "applied-by=uefn-ducky-unity-mcp\n",
                encoding="utf-8",
            )
            changed = True
    except OSError as exc:
        return {"ok": False, "changed": False, "error": str(exc)}
    return {
        "ok": True,
        "changed": changed,
        "script": str(script_path),
        "marker": str(marker_path),
    }


def configure_project(project_root: Path | str) -> dict[str, Any]:
    root = Path(project_root)
    if not is_unity_project(root):
        return {"ok": False, "path": str(root), "error": "not a Unity project"}
    manifest = root / "Packages" / "manifest.json"
    pkg = ensure_package_in_manifest(manifest)
    boot = ensure_bootstrap(root)
    ok = bool(pkg.get("ok")) and bool(boot.get("ok"))
    return {
        "ok": ok,
        "path": str(root),
        "package": pkg,
        "bootstrap": boot,
        "changed": bool(pkg.get("changed") or boot.get("changed")),
        "error": pkg.get("error") or boot.get("error") or "",
    }


def sync_open_projects(*, hub_path: Path | None = None) -> dict[str, Any]:
    hub = list_hub_projects(hub_path=hub_path)
    open_projects = list_open_hub_projects(hub_path=hub_path)
    results: list[dict[str, Any]] = []
    configured: list[str] = []
    with _STATE_LOCK:
        _STATE["hub_projects"] = [p.get("path") for p in hub]
        _STATE["open_projects"] = [p.get("path") for p in open_projects]
        if not open_projects:
            _STATE.update(
                phase="waiting",
                detail="Waiting for an open Unity Hub project",
                error="",
                configured=[],
                last_results=[],
            )
            return {
                "ok": True,
                "phase": "waiting",
                "open_projects": [],
                "configured": [],
                "results": [],
            }
        _STATE.update(phase="importing", detail="Configuring open Unity projects", error="")

    for proj in open_projects:
        result = configure_project(proj["path"])
        results.append(result)
        if result.get("ok"):
            configured.append(str(proj["path"]))

    errors = [r.get("error") for r in results if not r.get("ok") and r.get("error")]
    phase = "ready" if configured and not errors else ("error" if errors else "waiting")
    with _STATE_LOCK:
        _STATE.update(
            phase=phase,
            detail=f"{len(configured)} project(s) configured" if configured else "no projects",
            error="; ".join(str(e) for e in errors),
            configured=configured,
            last_results=results,
        )
    return {
        "ok": not bool(errors),
        "phase": phase,
        "open_projects": [p.get("path") for p in open_projects],
        "configured": configured,
        "results": results,
    }


def projects_status() -> dict[str, Any]:
    with _STATE_LOCK:
        return {
            "phase": _STATE.get("phase") or "idle",
            "detail": _STATE.get("detail") or "",
            "error": _STATE.get("error") or "",
            "hub_projects": list(_STATE.get("hub_projects") or []),
            "open_projects": list(_STATE.get("open_projects") or []),
            "configured": list(_STATE.get("configured") or []),
            "last_results": list(_STATE.get("last_results") or []),
            "watching": bool(_WATCH_THREAD and _WATCH_THREAD.is_alive()),
        }


def _watch_loop(log_fn: Callable[[str], None] | None) -> None:
    while not _WATCH_STOP.is_set():
        try:
            sync_open_projects()
        except Exception as exc:
            log.warning("project sync failed: %s", exc)
            with _STATE_LOCK:
                _STATE.update(phase="error", error=str(exc))
            if log_fn:
                try:
                    log_fn(f"UNITY MCP project sync failed: {exc}")
                except Exception:
                    pass
        _WATCH_STOP.wait(WATCH_INTERVAL_S)


def start_watcher(log_fn: Callable[[str], None] | None = None) -> None:
    global _WATCH_THREAD
    stop_watcher()
    _WATCH_STOP.clear()
    # Immediate first pass
    try:
        sync_open_projects()
    except Exception as exc:
        log.warning("initial project sync failed: %s", exc)
    thread = threading.Thread(
        target=_watch_loop,
        args=(log_fn,),
        daemon=True,
        name="unity-mcp-project-watch",
    )
    _WATCH_THREAD = thread
    thread.start()


def stop_watcher() -> None:
    global _WATCH_THREAD
    _WATCH_STOP.set()
    thread = _WATCH_THREAD
    _WATCH_THREAD = None
    if thread and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=2.0)
    with _STATE_LOCK:
        if _STATE.get("phase") not in ("error",):
            _STATE["phase"] = "idle"
