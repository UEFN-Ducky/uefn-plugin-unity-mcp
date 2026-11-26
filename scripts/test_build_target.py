"""--target in build_zip.py: host detection, the python_abi check, no cross-compiles, release names."""

import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_zip as bz  # noqa: E402


@pytest.mark.parametrize("machine,want", [("arm64", "macos-arm64"), ("x86_64", "macos-x64")])
def test_mac_host_target(monkeypatch, machine, want):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("platform.machine", lambda: machine)
    assert bz.host_target() == want
    assert f"cpython-313-darwin-{machine}".endswith(bz.TARGET_ABI[want])


def test_host_target_is_known():
    assert bz.host_target() in bz.TARGET_ABI


def test_check_target_reads_python_abi(tmp_path):
    z = tmp_path / "p.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("plugin.json", json.dumps({"python_abi": "cpython-313-x86_64-linux-gnu"}))
    bz.check_target(z, "linux-x86_64")
    for wrong in ("linux-arm64", "windows-x86_64"):
        with pytest.raises(SystemExit):
            bz.check_target(z, wrong)


def test_other_platform_is_refused():
    other = next(t for t in sorted(bz.TARGET_ABI) if t != bz.host_target())
    with pytest.raises(SystemExit, match="cross-compile"):
        bz.build_compiled_zip(target=other)


def test_zip_names_match_the_release(monkeypatch, tmp_path):
    """release_platforms finds deploy/*-<target>-compiled.ducky-plugin.zip; Windows keeps -compiled."""
    monkeypatch.setattr(bz, "OUT_DIR", tmp_path)
    monkeypatch.setattr(bz, "_find_ducky_repo", lambda: tmp_path)
    monkeypatch.setattr(bz, "check_target", lambda dest, target: None)
    monkeypatch.setattr(bz, "host_target", lambda: "linux-x86_64")
    monkeypatch.setattr(bz.subprocess, "run", lambda cmd, **kw: Path(cmd[-1]).write_bytes(b"zip"))
    manifest = json.loads((bz.ROOT / "plugin.json").read_text(encoding="utf-8"))
    stem = f"{str(manifest['id']).strip()}-{manifest.get('version') or 1}"

    win = bz.build_compiled_zip()
    assert win.name == f"{stem}-compiled.ducky-plugin.zip"
    linux = bz.build_compiled_zip(target="linux-x86_64")
    assert linux.name == f"{stem}-linux-x86_64-compiled.ducky-plugin.zip"
    assert win.exists()  # a platform build prunes only its own platform's zips
