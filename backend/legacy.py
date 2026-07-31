"""Removes the nested ``unity`` mcp.json row that plugin versions <= 1.1 created."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .constants import HTTP_PORT, LOCAL_HOSTS, NESTED_SERVER_ID


def remove_legacy_nested_server() -> dict[str, Any]:
    """Drop our old row; leave a hand-made ``unity`` server alone."""
    try:
        from backend.mcp_plugins.store import delete_mcp_server, load_plugin_manifest
    except Exception as exc:  # host internals unavailable (tests, older app)
        return {"removed": False, "error": str(exc)}

    try:
        manifest = load_plugin_manifest(NESTED_SERVER_ID)
    except Exception as exc:
        return {"removed": False, "error": str(exc)}
    if not manifest:
        return {"removed": False, "reason": "absent"}

    server = manifest.get("server") if isinstance(manifest.get("server"), dict) else {}
    url = str(server.get("url") or "")
    if not is_plugin_owned_url(url):
        return {"removed": False, "reason": "user-owned", "url": url}

    try:
        removed = bool(delete_mcp_server(NESTED_SERVER_ID))
    except Exception as exc:
        return {"removed": False, "error": str(exc)}
    return {"removed": removed, "url": url}


def is_plugin_owned_url(url: str) -> bool:
    parsed = urlparse(url)
    return (parsed.hostname or "") in LOCAL_HOSTS and parsed.port == HTTP_PORT
