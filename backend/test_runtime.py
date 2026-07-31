"""Tests for verified uv acquisition, probe, and server lifecycle."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend import runtime
from backend.constants import DEFAULT_URL, UV_VERSION


def _fake_uv_zip(exe_name: str = "uv.exe") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(exe_name, b"fake-uv-binary")
        zf.writestr("uvx.exe", b"fake-uvx-binary")
    return buf.getvalue()


def test_probe_http_unreachable() -> None:
    with patch.object(runtime.urllib.request, "urlopen", side_effect=OSError("down")):
        result = runtime.probe_http("http://127.0.0.1:1/mcp")
    assert result["reachable"] is False


def test_probe_http_http_error_counts_as_reachable() -> None:
    import urllib.error

    err = urllib.error.HTTPError(
        url="http://127.0.0.1:8080/",
        code=404,
        msg="Not Found",
        hdrs=None,
        fp=None,
    )
    with patch.object(runtime.urllib.request, "urlopen", side_effect=err):
        result = runtime.probe_http(DEFAULT_URL)
    assert result["reachable"] is True
    assert result["http_status"] == 404


def test_ensure_uv_checksum_and_extract(tmp_path: Path) -> None:
    data = _fake_uv_zip()
    digest = hashlib.sha256(data).hexdigest()
    meta = {
        "filename": "uv-x86_64-pc-windows-msvc.zip",
        "sha256": digest,
        "archive": "zip",
        "exe": "uv.exe",
    }
    with (
        patch.object(runtime, "_platform_key", return_value="win_amd64"),
        patch.object(runtime, "UV_ARTIFACTS", {"win_amd64": meta}),
        patch.object(runtime, "bin_dir", return_value=tmp_path / "bin"),
        patch.object(runtime, "_find_uv", return_value=None),
        patch.object(runtime, "_download", return_value=data),
        patch.object(runtime, "_LOCK", runtime.threading.Lock()),
    ):
        # Reset state under lock
        with runtime._LOCK:
            runtime._STATE.update(phase="idle", error="", uv_path="")
        result = runtime.ensure_uv(force=True)
    assert result["ok"] is True
    assert result["downloaded"] is True
    assert Path(result["uv_path"]).is_file()


def test_ensure_uv_checksum_mismatch(tmp_path: Path) -> None:
    data = _fake_uv_zip()
    meta = {
        "filename": "uv-x86_64-pc-windows-msvc.zip",
        "sha256": "0" * 64,
        "archive": "zip",
        "exe": "uv.exe",
    }
    with (
        patch.object(runtime, "_platform_key", return_value="win_amd64"),
        patch.object(runtime, "UV_ARTIFACTS", {"win_amd64": meta}),
        patch.object(runtime, "bin_dir", return_value=tmp_path / "bin"),
        patch.object(runtime, "_find_uv", return_value=None),
        patch.object(runtime, "_download", return_value=data),
    ):
        with runtime._LOCK:
            runtime._STATE.update(phase="idle", error="", uv_path="")
        result = runtime.ensure_uv(force=True)
    assert result["ok"] is False
    assert "checksum" in str(result.get("error") or "").lower()


def test_ensure_server_reuses_reachable() -> None:
    with (
        patch.object(
            runtime,
            "probe_http",
            return_value={"reachable": True, "http_status": 200},
        ),
        patch.object(runtime, "_server_alive", return_value=False),
    ):
        with runtime._LOCK:
            runtime._PROC = None
            runtime._STATE.update(owned=False, phase="idle")
        result = runtime.ensure_server()
    assert result["ok"] is True
    assert result["reused"] is True
    assert result["owned"] is False


def test_ensure_server_starts_process() -> None:
    fake_proc = MagicMock()
    fake_proc.pid = 4242
    fake_proc.poll.return_value = None

    with (
        patch.object(runtime, "probe_http", return_value={"reachable": False}),
        patch.object(runtime, "_server_alive", return_value=False),
        patch.object(
            runtime,
            "ensure_uv",
            return_value={"ok": True, "uv_path": "C:/fake/uv.exe"},
        ),
        patch.object(runtime.subprocess, "Popen", return_value=fake_proc) as popen,
        patch.object(runtime.Path, "is_file", return_value=False),
    ):
        with runtime._LOCK:
            runtime._PROC = None
            runtime._STATE.update(owned=False, phase="idle", server_pid=None)
        result = runtime.ensure_server()
    assert result["ok"] is True
    assert result["started"] is True
    assert result["pid"] == 4242
    assert popen.called
    argv = popen.call_args[0][0]
    assert "mcpforunityserver" in " ".join(argv) or any(
        "mcpforunityserver" in str(a) for a in argv
    )


def test_stop_server_only_owned() -> None:
    with runtime._LOCK:
        runtime._PROC = None
        runtime._STATE.update(owned=False, server_pid=None)
    result = runtime.stop_server()
    assert result["ok"] is True
    assert result["stopped"] is False


def test_runtime_status_shape() -> None:
    with patch.object(
        runtime,
        "probe_http",
        return_value={"reachable": False, "error": "x"},
    ):
        status = runtime.runtime_status()
    assert status["url"] == DEFAULT_URL
    assert status["uv_version"] == UV_VERSION
    assert "phase" in status
    assert "probe" in status
