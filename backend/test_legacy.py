"""Cleanup of the nested mcp.json row created by plugin versions <= 1.1."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from backend import legacy


@pytest.fixture
def host_store(monkeypatch):
    """Stub ``backend.mcp_plugins.store`` the way the app exposes it."""
    store = types.ModuleType("backend.mcp_plugins.store")
    store.load_plugin_manifest = MagicMock(return_value=None)
    store.delete_mcp_server = MagicMock(return_value=True)
    package = types.ModuleType("backend.mcp_plugins")
    package.store = store
    monkeypatch.setitem(sys.modules, "backend.mcp_plugins", package)
    monkeypatch.setitem(sys.modules, "backend.mcp_plugins.store", store)
    return store


def test_removes_our_local_row(host_store) -> None:
    host_store.load_plugin_manifest.return_value = {
        "server": {"type": "http", "url": "http://127.0.0.1:8080/mcp"}
    }
    result = legacy.remove_legacy_nested_server()
    assert result["removed"] is True
    host_store.delete_mcp_server.assert_called_once_with("unity")


def test_keeps_a_user_owned_unity_server(host_store) -> None:
    host_store.load_plugin_manifest.return_value = {
        "server": {"type": "http", "url": "http://unity.example.com/mcp"}
    }
    result = legacy.remove_legacy_nested_server()
    assert result["removed"] is False
    assert result["reason"] == "user-owned"
    assert not host_store.delete_mcp_server.called


def test_absent_row_is_not_an_error(host_store) -> None:
    result = legacy.remove_legacy_nested_server()
    assert result == {"removed": False, "reason": "absent"}


def test_delete_failure_is_reported(host_store) -> None:
    host_store.load_plugin_manifest.return_value = {
        "server": {"url": "http://localhost:8080/mcp"}
    }
    host_store.delete_mcp_server.side_effect = ValueError("catalog server")
    result = legacy.remove_legacy_nested_server()
    assert result == {"removed": False, "error": "catalog server"}


def test_missing_host_module_is_tolerated(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "backend.mcp_plugins.store", None)
    result = legacy.remove_legacy_nested_server()
    assert result["removed"] is False
    assert "error" in result
