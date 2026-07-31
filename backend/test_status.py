"""Status aggregation + thin register surface."""

from __future__ import annotations

import json
from unittest.mock import patch

import backend as plugin


class FakeApi:
    """Collects tools the plugin registers, without touching the host."""

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.tools: dict[str, object] = {}

    def is_enabled(self) -> bool:
        return self.enabled

    def log(self, msg: str) -> None:
        return None

    def tool(self, **kwargs):  # type: ignore[no-untyped-def]
        def deco(fn):  # type: ignore[no-untyped-def]
            self.tools[kwargs.get("name") or fn.__name__] = fn
            return fn

        return deco


def _register(api: FakeApi) -> FakeApi:
    with patch("backend.legacy.remove_legacy_nested_server", return_value={"removed": False}):
        plugin.register(api)
    return api


def test_build_status_waiting_for_unity() -> None:
    with (
        patch("backend.runtime.runtime_status") as rt,
        patch("backend.projects.projects_status") as proj,
        patch.object(plugin, "_tools_status", return_value={"available": True, "count": 0}),
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
        status = plugin._build_status()
    assert status["state"] == "waiting_for_unity"
    assert status["ok"] is False


def test_build_status_ready() -> None:
    with (
        patch("backend.runtime.runtime_status") as rt,
        patch("backend.projects.projects_status") as proj,
        patch.object(
            plugin,
            "_tools_status",
            return_value={"available": True, "count": 12, "names": ["manage_scene"]},
        ),
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
        status = plugin._build_status()
    assert status["state"] == "ready"
    assert status["ok"] is True
    assert "unity_list_tools" in status["hint"]
    assert status["tools"]["count"] == 12


def test_tools_status_skips_probe_when_unreachable() -> None:
    with patch("backend.client.list_tools") as list_tools:
        status = plugin._tools_status(False)
    assert status["available"] is False
    assert not list_tools.called


def test_register_registers_plugin_owned_tools() -> None:
    api = _register(FakeApi())
    assert set(api.tools) == {
        "unity_status",
        "unity_list_tools",
        "unity_call",
        "unity_redeploy",
    }


def test_register_drops_legacy_nested_row() -> None:
    with patch(
        "backend.legacy.remove_legacy_nested_server",
        return_value={"removed": True, "url": "http://127.0.0.1:8080/mcp"},
    ) as cleanup:
        plugin.register(FakeApi())
    assert cleanup.called


def test_unload_stops_runtime() -> None:
    with (
        patch("backend.projects.stop_watcher") as stop_w,
        patch("backend.runtime.stop_server") as stop_s,
    ):
        plugin.unload()
    assert stop_w.called
    assert stop_s.called


def test_unity_status_tool_json() -> None:
    api = _register(FakeApi())
    with patch.object(
        plugin,
        "_build_status",
        return_value={"ok": False, "state": "waiting_for_unity", "plugin_id": "unity-mcp"},
    ):
        payload = json.loads(api.tools["unity_status"]())
    assert payload["state"] == "waiting_for_unity"
    assert payload["plugin_id"] == "unity-mcp"


def test_unity_list_tools_reports_error_with_status() -> None:
    api = _register(FakeApi())
    with (
        patch("backend.client.list_tools", side_effect=TimeoutError("no answer")),
        patch.object(plugin, "_build_status", return_value={"state": "connecting"}),
    ):
        payload = json.loads(api.tools["unity_list_tools"]())
    assert payload["ok"] is False
    assert "no answer" in payload["error"]
    assert payload["status"]["state"] == "connecting"


def test_unity_call_forwards_arguments() -> None:
    api = _register(FakeApi())
    with patch("backend.client.call_tool", return_value={"ok": True, "text": "done"}) as call:
        payload = json.loads(api.tools["unity_call"]("manage_scene", {"action": "load"}))
    call.assert_called_once_with("manage_scene", {"action": "load"})
    assert payload["text"] == "done"


def test_unity_call_accepts_json_string_arguments() -> None:
    api = _register(FakeApi())
    with patch("backend.client.call_tool", return_value={"ok": True}) as call:
        api.tools["unity_call"]("manage_scene", '{"action": "load"}')
    call.assert_called_once_with("manage_scene", {"action": "load"})


def test_unity_call_rejects_bad_arguments() -> None:
    api = _register(FakeApi())
    payload = json.loads(api.tools["unity_call"]("manage_scene", "not json"))
    assert payload["ok"] is False
    assert "valid JSON" in payload["error"]


def test_unity_call_requires_tool_name() -> None:
    api = _register(FakeApi())
    payload = json.loads(api.tools["unity_call"](" "))
    assert payload["ok"] is False
