"""--target in build_zip.py: host detection, the python_abi check, and no cross-compiles."""

import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_zip as bz  # noqa: E402


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
