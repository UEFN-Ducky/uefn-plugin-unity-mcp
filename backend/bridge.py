"""Nested MCP server upsert into the host mcp.json (existing public APIs only)."""

from __future__ import annotations

from typing import Any

from .constants import DEFAULT_URL, DESCRIPTION, NESTED_SERVER_ID, UNITY_INTENTS


def upsert_nested_server(url: str = DEFAULT_URL) -> dict[str, Any]:
    from backend.mcp_plugins.bridge_proxy import schedule_sync_nested_proxies
    from backend.mcp_plugins.store import (
        create_mcp_server,
        load_plugin_manifest,
        set_mcp_server_enabled,
        update_mcp_server_manifest,
    )

    existing = load_plugin_manifest(NESTED_SERVER_ID)
    if existing is None:
        create_mcp_server(
            NESTED_SERVER_ID,
            "UNITY MCP",
            description=DESCRIPTION,
            transport="http",
            url=url,
            tool_prefix="unity",
            intents=list(UNITY_INTENTS),
        )
        action = "created"
    else:
        update_mcp_server_manifest(
            NESTED_SERVER_ID,
            {
                "label": "UNITY MCP",
                "description": DESCRIPTION,
                "tool_prefix": "unity",
                "intents": list(UNITY_INTENTS),
                "kind": "custom",
                "server": {"type": "http", "url": url, "headers": {}},
            },
        )
        action = "updated"

    enabled_info = set_mcp_server_enabled(NESTED_SERVER_ID, True)
    schedule_sync_nested_proxies()
    return {
        "action": action,
        "server_id": NESTED_SERVER_ID,
        "url": url,
        "enabled": True,
        "enabled_mcp_plugins": enabled_info.get("enabled_mcp_plugins"),
    }


def disable_nested_server() -> dict[str, Any]:
    try:
        from backend.mcp_plugins.bridge_proxy import schedule_sync_nested_proxies
        from backend.mcp_plugins.store import set_mcp_server_enabled

        info = set_mcp_server_enabled(NESTED_SERVER_ID, False)
        schedule_sync_nested_proxies()
        return {"ok": True, "enabled": False, "info": info}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def nested_status() -> dict[str, Any]:
    try:
        from backend.mcp_plugins.store import get_enabled_plugin_ids, load_plugin_manifest

        manifest = load_plugin_manifest(NESTED_SERVER_ID)
        if not manifest:
            return {"configured": False, "enabled": False}
        server = manifest.get("server") if isinstance(manifest.get("server"), dict) else {}
        enabled = NESTED_SERVER_ID in get_enabled_plugin_ids()
        return {
            "configured": True,
            "enabled": enabled,
            "url": str(server.get("url") or ""),
            "tool_prefix": str(manifest.get("tool_prefix") or "unity"),
            "label": str(manifest.get("label") or ""),
        }
    except Exception as exc:
        return {"configured": False, "error": str(exc)}
