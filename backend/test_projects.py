"""Tests for Hub discovery, manifest inject, bootstrap, open-project filter."""

from __future__ import annotations

import json
import time
from pathlib import Path

from backend import projects
from backend.constants import BOOTSTRAP_SCRIPT_NAME, UNITY_PACKAGE_GIT, UNITY_PACKAGE_ID


def _make_unity_project(root: Path, *, open_project: bool = False) -> Path:
    (root / "Assets").mkdir(parents=True)
    (root / "ProjectSettings").mkdir(parents=True)
    (root / "Packages").mkdir(parents=True)
    (root / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 2022.3.0f1\n",
        encoding="utf-8",
    )
    (root / "Packages" / "manifest.json").write_text(
        json.dumps(
            {
                "dependencies": {
                    "com.unity.modules.ui": "1.0.0",
                    "com.unity.test-framework": "1.1.31",
                },
                "scopedRegistries": [
                    {
                        "name": "example",
                        "url": "https://example.com",
                        "scopes": ["com.example"],
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if open_project:
        (root / "Temp").mkdir(parents=True)
        (root / "Temp" / "UnityLockfile").write_text("", encoding="utf-8")
    return root


def test_parse_hub_projects_v1() -> None:
    raw = {
        "schema_version": "v1",
        "data": {
            "C:/Games/Alpha": {
                "title": "Alpha",
                "path": "C:/Games/Alpha",
                "version": "2022.3.0f1",
            },
            "C:/Games/Beta": {
                "title": "Beta",
                "path": "C:/Games/Beta",
                "version": "6000.0.0f1",
            },
        },
    }
    parsed = projects.parse_hub_projects(raw)
    assert len(parsed) == 2
    assert parsed[0]["title"] == "Alpha"
    assert parsed[1]["path"] == "C:/Games/Beta"


def test_list_open_hub_projects_filters_lockfile(tmp_path: Path) -> None:
    open_p = _make_unity_project(tmp_path / "OpenProj", open_project=True)
    closed_p = _make_unity_project(tmp_path / "ClosedProj", open_project=False)
    hub = tmp_path / "projects-v1.json"
    hub.write_text(
        json.dumps(
            {
                "schema_version": "v1",
                "data": {
                    str(open_p): {"title": "Open", "path": str(open_p)},
                    str(closed_p): {"title": "Closed", "path": str(closed_p)},
                },
            }
        ),
        encoding="utf-8",
    )
    opened = projects.list_open_hub_projects(hub_path=hub)
    assert [p["path"] for p in opened] == [str(open_p.resolve())]


def test_ensure_package_in_manifest_idempotent_and_preserves(tmp_path: Path) -> None:
    proj = _make_unity_project(tmp_path / "Game")
    manifest = proj / "Packages" / "manifest.json"
    first = projects.ensure_package_in_manifest(manifest)
    assert first["ok"] is True
    assert first["changed"] is True
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["dependencies"][UNITY_PACKAGE_ID] == UNITY_PACKAGE_GIT
    assert data["dependencies"]["com.unity.modules.ui"] == "1.0.0"
    assert data["scopedRegistries"][0]["name"] == "example"

    second = projects.ensure_package_in_manifest(manifest)
    assert second["ok"] is True
    assert second["changed"] is False


def test_ensure_bootstrap_writes_script(tmp_path: Path) -> None:
    proj = _make_unity_project(tmp_path / "Boot")
    result = projects.ensure_bootstrap(proj)
    assert result["ok"] is True
    assert result["changed"] is True
    script = proj / "Assets" / "Editor" / BOOTSTRAP_SCRIPT_NAME
    text = script.read_text(encoding="utf-8")
    assert "MCPForUnity.AutoStartOnLoad" in text
    assert "MCPForUnity.UseHttpTransport" in text
    assert "InitializeOnLoad" in text

    again = projects.ensure_bootstrap(proj)
    assert again["ok"] is True
    assert again["changed"] is False


def test_sync_open_projects_configures(tmp_path: Path) -> None:
    open_p = _make_unity_project(tmp_path / "Live", open_project=True)
    hub = tmp_path / "hub.json"
    hub.write_text(
        json.dumps(
            {
                "schema_version": "v1",
                "data": {str(open_p): {"title": "Live", "path": str(open_p)}},
            }
        ),
        encoding="utf-8",
    )
    result = projects.sync_open_projects(hub_path=hub)
    assert result["ok"] is True
    assert result["phase"] == "ready"
    assert len(result["configured"]) == 1
    manifest = json.loads(
        (open_p / "Packages" / "manifest.json").read_text(encoding="utf-8")
    )
    assert UNITY_PACKAGE_ID in manifest["dependencies"]


def test_sync_waiting_when_none_open(tmp_path: Path) -> None:
    closed = _make_unity_project(tmp_path / "Idle", open_project=False)
    hub = tmp_path / "hub.json"
    hub.write_text(
        json.dumps(
            {
                "schema_version": "v1",
                "data": {str(closed): {"title": "Idle", "path": str(closed)}},
            }
        ),
        encoding="utf-8",
    )
    result = projects.sync_open_projects(hub_path=hub)
    assert result["phase"] == "waiting"
    assert result["configured"] == []


def test_watcher_start_stop(tmp_path: Path) -> None:
    open_p = _make_unity_project(tmp_path / "WatchMe", open_project=True)
    hub = tmp_path / "hub.json"
    hub.write_text(
        json.dumps(
            {
                "schema_version": "v1",
                "data": {str(open_p): {"title": "W", "path": str(open_p)}},
            }
        ),
        encoding="utf-8",
    )
    # Patch hub path resolution by syncing once with hub_path, then start watcher
    # which uses default hub path — for unit test call sync directly + stop.
    projects.stop_watcher()
    projects.sync_open_projects(hub_path=hub)
    status = projects.projects_status()
    assert "WatchMe" in str(status.get("configured") or status.get("open_projects"))
    projects.start_watcher(None)
    time.sleep(0.2)
    assert projects.projects_status().get("watching") is True
    projects.stop_watcher()
    assert projects.projects_status().get("watching") is False
