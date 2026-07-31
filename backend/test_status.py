"""Status aggregation + thin register surface."""

from __future__ import annotations

import json
from unittest.mock import patch

import backend as plugin


def test_build_status_waiting_for_unity() -> None:
    with (
        patch.object(
            plugin,
            "_build_status",
            wraps=plugin._build_status,
        ),
        patch("backend.runtime.runtime_status") as rt,
        patch("backend.projects.projects_status") as proj,
        patch("backend.bridge.nested_status") as nested,
    ):
        rt.return_value = {
            "phase": "ready",
            "probe": {"reachable": True},
            "detail": "",
            "error": "",
        }
        proj.return_value = {
            "phase": "waiting",
            "open_projects": [],
            "configured": [],
            "detail": "",
            "error": "",
        }
        nested.return_value = {"configured": True, "enabled": True}
        status = plugin._build_status()
    assert status["state"] == "waiting_for_unity"
    assert status["ok"] is False


def test_build_status_ready() -> None:
    with (
        patch("backend.runtime.runtime_status") as rt,
        patch("backend.projects.projects_status") as proj,
        patch("backend.bridge.nested_status") as nested,
    ):
        rt.return_value = {
            "phase": "ready",
            "probe": {"reachable": True},
            "detail": "",
            "error": "",
        }
        proj.return_value = {
            "phase": "ready",
            "open_projects": ["C:/Game"],
            "configured": ["C:/Game"],
            "detail": "",
            "error": "",
        }
        nested.return_value = {"configured": True, "enabled": True}
        status = plugin._build_status()
    assert status["state"] == "ready"
    assert status["ok"] is True
    assert "unity__" in status["hint"] or "Ready" in status["hint"]


def test_register_registers_tools_without_blocking() -> None:
    tools: list[str] = []

    class Api:
        def is_enabled(self) -> bool:
            return False

        def log(self, msg: str) -> None:
            return None

        def tool(self, **kwargs):  # type: ignore[no-untyped-def]
            def deco(fn):  # type: ignore[no-untyped-def]
                tools.append(kwargs.get("name") or fn.__name__)
                return fn

            return deco

    with patch("backend.bridge.upsert_nested_server", return_value={"action": "created"}):
        plugin.register(Api())
    assert "unity_mcp_status" in tools
    assert "unity_mcp_redeploy" in tools


def test_unload_stops_and_disables() -> None:
    with (
        patch("backend.projects.stop_watcher") as stop_w,
        patch("backend.runtime.stop_server") as stop_s,
        patch("backend.bridge.disable_nested_server", return_value={"ok": True}) as disable,
    ):
        plugin.unload()
    assert stop_w.called
    assert stop_s.called
    assert disable.called


def test_unity_mcp_status_tool_json() -> None:
    captured = {}

    class Api:
        def is_enabled(self) -> bool:
            return False

        def log(self, msg: str) -> None:
            return None

        def tool(self, **kwargs):  # type: ignore[no-untyped-def]
            def deco(fn):  # type: ignore[no-untyped-def]
                captured[kwargs.get("name")] = fn
                return fn

            return deco

    with (
        patch("backend.bridge.upsert_nested_server", return_value={"action": "updated"}),
        patch.object(
            plugin,
            "_build_status",
            return_value={"ok": False, "state": "waiting_for_unity", "plugin_id": "unity-mcp"},
        ),
    ):
        plugin.register(Api())
        payload = json.loads(captured["unity_mcp_status"]())
    assert payload["state"] == "waiting_for_unity"
    assert payload["plugin_id"] == "unity-mcp"
