"""In-process MCP client for the local Coplay Unity server.

The plugin owns the connection so Unity shows up as one Store plugin (like
Blender) instead of a nested ``mcp.json`` server row.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Awaitable, Callable

from .constants import CALL_TIMEOUT_S, CONNECT_TIMEOUT_S, DEFAULT_URL

log = logging.getLogger("uefn.plugin.unity-mcp.client")

_TOTAL_TIMEOUT_S = CONNECT_TIMEOUT_S + CALL_TIMEOUT_S


class UnityMcpError(RuntimeError):
    """Readable failure talking to the local Unity MCP server."""


def describe_error(exc: BaseException) -> str:
    """Flatten anyio task groups — their default text says nothing useful."""
    nested = getattr(exc, "exceptions", None)
    if nested:
        return "; ".join(describe_error(sub) for sub in nested)
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def list_tools() -> list[dict[str, Any]]:
    """Live Unity Editor tools with their input schemas."""

    async def run(session: Any) -> list[dict[str, Any]]:
        result = await asyncio.wait_for(session.list_tools(), timeout=CALL_TIMEOUT_S)
        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema or {},
            }
            for tool in (result.tools or [])
        ]

    return _with_session(run)


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Invoke one Unity Editor tool and flatten its result to text."""

    async def run(session: Any) -> dict[str, Any]:
        result = await asyncio.wait_for(
            session.call_tool(name, arguments or {}),
            timeout=CALL_TIMEOUT_S,
        )
        return {
            "ok": not bool(getattr(result, "isError", False)),
            "tool": name,
            "text": flatten_content(getattr(result, "content", None)),
            "structured": getattr(result, "structuredContent", None),
        }

    return _with_session(run)


def flatten_content(content: Any) -> str:
    parts: list[str] = []
    for block in content or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
            continue
        kind = str(getattr(block, "type", "") or type(block).__name__)
        parts.append(f"[{kind}]")
    return "\n".join(parts)


async def _session_scope(run: Callable[[Any], Awaitable[Any]]) -> Any:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    # Unity edits can run long; keep the HTTP read window above CALL_TIMEOUT_S.
    async with streamablehttp_client(DEFAULT_URL, timeout=CALL_TIMEOUT_S) as transport:
        read, write = transport[0], transport[1]
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout=CONNECT_TIMEOUT_S)
            return await run(session)


def _with_session(run: Callable[[Any], Awaitable[Any]]) -> Any:
    try:
        return run_isolated(lambda: _session_scope(run), timeout=_TOTAL_TIMEOUT_S)
    except Exception as exc:
        raise UnityMcpError(f"{describe_error(exc)} ({DEFAULT_URL})") from exc


def run_isolated(factory: Callable[[], Awaitable[Any]], *, timeout: float) -> Any:
    """Run one coroutine on a private loop — tool calls arrive on many threads."""
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = asyncio.run(factory())
        except BaseException as exc:  # noqa: BLE001 - re-raised to the caller
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True, name="unity-mcp-call")
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise TimeoutError(f"Unity MCP did not answer within {timeout:.0f}s ({DEFAULT_URL})")
    error = box.get("error")
    if error is not None:
        raise error
    return box.get("value")
