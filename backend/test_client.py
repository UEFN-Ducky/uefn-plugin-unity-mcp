"""In-process client plumbing: private loop, timeout, content flattening."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from backend import client


def test_run_isolated_returns_value_from_private_loop() -> None:
    async def work() -> str:
        await asyncio.sleep(0)
        return "ok"

    assert client.run_isolated(work, timeout=5) == "ok"


def test_run_isolated_reraises() -> None:
    async def boom() -> None:
        raise RuntimeError("unity is closed")

    with pytest.raises(RuntimeError, match="unity is closed"):
        client.run_isolated(boom, timeout=5)


def test_run_isolated_times_out() -> None:
    async def slow() -> None:
        await asyncio.sleep(5)

    with pytest.raises(TimeoutError):
        client.run_isolated(slow, timeout=0.2)


def test_run_isolated_works_inside_a_running_loop() -> None:
    async def outer() -> str:
        async def inner() -> str:
            return "nested"

        return client.run_isolated(inner, timeout=5)

    assert asyncio.run(outer()) == "nested"


def test_flatten_content_keeps_text_and_labels_other_blocks() -> None:
    blocks = [
        SimpleNamespace(type="text", text="scene loaded"),
        SimpleNamespace(type="image"),
    ]
    assert client.flatten_content(blocks) == "scene loaded\n[image]"


def test_flatten_content_handles_empty() -> None:
    assert client.flatten_content(None) == ""


def test_describe_error_unwraps_task_groups() -> None:
    group = ExceptionGroup(  # noqa: F821 - builtin on 3.11+
        "unhandled errors in a TaskGroup",
        [ConnectionRefusedError("All connection attempts failed")],
    )
    assert client.describe_error(group) == (
        "ConnectionRefusedError: All connection attempts failed"
    )


def test_with_session_raises_readable_error(monkeypatch) -> None:
    async def boom(_session: object) -> None:
        raise AssertionError("never runs")

    def explode(_factory, *, timeout: float) -> None:
        raise ConnectionError("All connection attempts failed")

    monkeypatch.setattr(client, "run_isolated", explode)
    with pytest.raises(client.UnityMcpError) as err:
        client._with_session(boom)
    assert "All connection attempts failed" in str(err.value)
    assert client.DEFAULT_URL in str(err.value)
