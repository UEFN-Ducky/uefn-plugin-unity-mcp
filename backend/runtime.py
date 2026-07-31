"""Managed uv + Coplay HTTP MCP server lifecycle (plugin-owned)."""

from __future__ import annotations

import hashlib
import io
import logging
import os
import shutil
import subprocess
import sys
import tarfile
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .constants import (
    DEFAULT_BASE_URL,
    DEFAULT_URL,
    DOWNLOAD_TIMEOUT_S,
    HTTP_HOST,
    HTTP_PORT,
    PROBE_TIMEOUT_S,
    SERVER_ENTRY,
    SERVER_PYPI,
    UV_ARTIFACTS,
    UV_RELEASE_BASE,
    UV_VERSION,
)

log = logging.getLogger("uefn.plugin.unity-mcp.runtime")

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {
    "phase": "idle",  # idle|downloading|starting|ready|error|waiting
    "detail": "",
    "url": DEFAULT_URL,
    "uv_path": "",
    "server_pid": None,
    "owned": False,
    "error": "",
}
_PROC: subprocess.Popen[Any] | None = None


def _appdata_root() -> Path:
    try:
        from backend.skills.store import appdata_dir

        return Path(appdata_dir()) / "unity_mcp"
    except Exception:
        local = os.environ.get("LOCALAPPDATA") or os.environ.get("HOME") or "."
        return Path(local) / "UEFN-Ducky" / "unity_mcp"


def runtime_root() -> Path:
    root = _appdata_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def bin_dir() -> Path:
    d = runtime_root() / "bin" / UV_VERSION
    d.mkdir(parents=True, exist_ok=True)
    return d


def _platform_key() -> str | None:
    if sys.platform == "win32":
        return "win_amd64"
    if sys.platform == "darwin":
        return "darwin_arm64" if os.uname().machine == "arm64" else "darwin_x86_64"
    if sys.platform.startswith("linux"):
        machine = os.uname().machine
        if machine in ("x86_64", "amd64"):
            return "linux_x86_64"
    return None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _find_uv() -> Path | None:
    key = _platform_key()
    if not key:
        return None
    meta = UV_ARTIFACTS[key]
    candidate = bin_dir() / meta["exe"]
    if candidate.is_file():
        return candidate
    # Also accept a previously extracted nested layout.
    for path in bin_dir().rglob(meta["exe"]):
        if path.is_file():
            return path
    which = shutil.which("uv")
    if which:
        return Path(which)
    return None


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "UEFN-Ducky-UNITY-MCP/1.1"})
    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_S) as resp:
        return resp.read()


def _extract_uv(archive: bytes, *, kind: str, exe_name: str, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    if kind == "zip":
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                parts = Path(info.filename).parts
                if ".." in parts or Path(info.filename).is_absolute():
                    continue
                if Path(info.filename).name != exe_name and not info.filename.endswith(
                    f"/{exe_name}"
                ):
                    # Keep uv.exe + uvx.exe if present; skip docs.
                    name = Path(info.filename).name.lower()
                    if name not in {exe_name.lower(), "uvx.exe", "uvx"}:
                        continue
                out = dest / Path(info.filename).name
                out.write_bytes(zf.read(info))
                if sys.platform != "win32":
                    out.chmod(0o755)
    else:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                name = Path(member.name).name
                if name not in {exe_name, "uvx"}:
                    continue
                out = dest / name
                extracted = tf.extractfile(member)
                if extracted is None:
                    continue
                out.write_bytes(extracted.read())
                out.chmod(0o755)
    found = dest / exe_name
    if not found.is_file():
        raise FileNotFoundError(f"{exe_name} missing after extract into {dest}")
    return found


def ensure_uv(*, force: bool = False) -> dict[str, Any]:
    """Return path to pinned uv, downloading with checksum verification if needed."""
    with _LOCK:
        existing = None if force else _find_uv()
        if existing is not None:
            _STATE["uv_path"] = str(existing)
            return {"ok": True, "uv_path": str(existing), "downloaded": False}

        key = _platform_key()
        if key is None or key not in UV_ARTIFACTS:
            _STATE.update(phase="error", error=f"unsupported platform: {sys.platform}")
            return {"ok": False, "error": _STATE["error"]}

        meta = UV_ARTIFACTS[key]
        url = f"{UV_RELEASE_BASE}/{meta['filename']}"
        _STATE.update(phase="downloading", detail=f"Downloading uv {UV_VERSION}", error="")
        try:
            data = _download(url)
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            _STATE.update(phase="error", error=f"uv download failed: {exc}")
            return {"ok": False, "error": _STATE["error"]}

        digest = _sha256(data)
        if digest.lower() != meta["sha256"].lower():
            _STATE.update(
                phase="error",
                error=f"uv checksum mismatch (got {digest}, want {meta['sha256']})",
            )
            return {"ok": False, "error": _STATE["error"]}

        try:
            path = _extract_uv(
                data,
                kind=meta["archive"],
                exe_name=meta["exe"],
                dest=bin_dir(),
            )
        except (OSError, zipfile.BadZipFile, tarfile.TarError) as exc:
            _STATE.update(phase="error", error=f"uv extract failed: {exc}")
            return {"ok": False, "error": _STATE["error"]}

        _STATE["uv_path"] = str(path)
        _STATE["detail"] = f"uv {UV_VERSION} ready"
        return {"ok": True, "uv_path": str(path), "downloaded": True}


def probe_http(url: str = DEFAULT_URL) -> dict[str, Any]:
    """Best-effort reachability (MCP streamable HTTP may not answer a plain GET)."""
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else url
    try:
        req = urllib.request.Request(
            base,
            method="GET",
            headers={"User-Agent": "UEFN-Ducky-UNITY-MCP/1.1", "Accept": "*/*"},
        )
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT_S) as resp:
            return {
                "reachable": True,
                "probe_url": base,
                "http_status": getattr(resp, "status", None) or resp.getcode(),
            }
    except urllib.error.HTTPError as exc:
        return {
            "reachable": True,
            "probe_url": base,
            "http_status": exc.code,
            "detail": str(exc.reason or exc),
        }
    except Exception as exc:
        return {"reachable": False, "probe_url": base, "error": str(exc)}


def _server_alive() -> bool:
    global _PROC
    if _PROC is None:
        return False
    code = _PROC.poll()
    if code is not None:
        _PROC = None
        _STATE["server_pid"] = None
        _STATE["owned"] = False
        return False
    return True


def ensure_server() -> dict[str, Any]:
    """Start Coplay HTTP MCP on 127.0.0.1:8080 if nothing healthy is listening."""
    global _PROC
    with _LOCK:
        probe = probe_http(DEFAULT_URL)
        if probe.get("reachable"):
            _STATE.update(
                phase="ready",
                detail="HTTP endpoint reachable",
                url=DEFAULT_URL,
                error="",
                owned=_server_alive(),
            )
            return {
                "ok": True,
                "url": DEFAULT_URL,
                "reused": True,
                "owned": bool(_STATE["owned"]),
                "probe": probe,
            }

        uv = ensure_uv()
        if not uv.get("ok"):
            return uv

        if _server_alive():
            # Process started but not reachable yet.
            _STATE.update(phase="starting", detail="Waiting for HTTP server", error="")
            return {
                "ok": True,
                "url": DEFAULT_URL,
                "starting": True,
                "owned": True,
                "pid": _STATE.get("server_pid"),
            }

        uv_path = str(uv["uv_path"])
        argv = [
            uv_path,
            "tool",
            "run",
            "--from",
            SERVER_PYPI,
            SERVER_ENTRY,
            "--transport",
            "http",
            "--http-url",
            DEFAULT_BASE_URL,
        ]
        # Prefer uvx if sibling exists.
        uvx = Path(uv_path).with_name("uvx.exe" if sys.platform == "win32" else "uvx")
        if uvx.is_file():
            argv = [
                str(uvx),
                "--from",
                SERVER_PYPI,
                SERVER_ENTRY,
                "--transport",
                "http",
                "--http-url",
                DEFAULT_BASE_URL,
            ]

        _STATE.update(phase="starting", detail="Starting mcpforunityserver", error="")
        popen_kwargs: dict[str, Any] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "stdin": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        env = os.environ.copy()
        env["UNITY_MCP_TRANSPORT"] = "http"
        env["UNITY_MCP_HTTP_URL"] = DEFAULT_BASE_URL
        env["UNITY_MCP_HTTP_HOST"] = HTTP_HOST
        env["UNITY_MCP_HTTP_PORT"] = str(HTTP_PORT)
        env["UNITY_MCP_SKIP_STARTUP_CONNECT"] = "1"

        try:
            _PROC = subprocess.Popen(argv, env=env, **popen_kwargs)
        except OSError as exc:
            _STATE.update(phase="error", error=f"server start failed: {exc}")
            return {"ok": False, "error": _STATE["error"], "argv": argv}

        _STATE.update(
            server_pid=_PROC.pid,
            owned=True,
            url=DEFAULT_URL,
            detail=f"server pid {_PROC.pid}",
        )
        return {
            "ok": True,
            "url": DEFAULT_URL,
            "started": True,
            "owned": True,
            "pid": _PROC.pid,
            "argv": argv,
        }


def stop_server() -> dict[str, Any]:
    """Stop the plugin-owned server process (never kill a reused external one)."""
    global _PROC
    with _LOCK:
        if _PROC is None or not _STATE.get("owned"):
            _PROC = None
            _STATE.update(server_pid=None, owned=False, phase="idle", detail="stopped")
            return {"ok": True, "stopped": False}
        proc = _PROC
        _PROC = None
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
        except Exception as exc:
            _STATE.update(phase="error", error=f"stop failed: {exc}")
            return {"ok": False, "error": str(exc)}
        _STATE.update(server_pid=None, owned=False, phase="idle", detail="stopped", error="")
        return {"ok": True, "stopped": True}


def runtime_status() -> dict[str, Any]:
    probe = probe_http(DEFAULT_URL)
    alive = _server_alive()
    phase = str(_STATE.get("phase") or "idle")
    if probe.get("reachable"):
        phase = "ready"
    elif phase in ("idle", "waiting") and not alive:
        phase = "waiting"
    elif alive and not probe.get("reachable"):
        phase = "starting"
    return {
        "phase": phase,
        "detail": _STATE.get("detail") or "",
        "error": _STATE.get("error") or "",
        "url": DEFAULT_URL,
        "uv_path": _STATE.get("uv_path") or str(_find_uv() or ""),
        "server_pid": _STATE.get("server_pid"),
        "owned": bool(_STATE.get("owned") and alive),
        "probe": probe,
        "uv_version": UV_VERSION,
        "server_package": SERVER_PYPI,
    }


def set_phase(phase: str, *, detail: str = "", error: str = "") -> None:
    with _LOCK:
        _STATE["phase"] = phase
        if detail:
            _STATE["detail"] = detail
        if error or phase == "error":
            _STATE["error"] = error
