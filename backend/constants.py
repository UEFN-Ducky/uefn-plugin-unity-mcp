"""Shared constants for the UNITY MCP Store plugin."""

from __future__ import annotations

PLUGIN_ID = "unity-mcp"
# Nested mcp.json row created by plugin versions <= 1.1; cleaned up on load.
NESTED_SERVER_ID = "unity"
DEFAULT_URL = "http://127.0.0.1:8080/mcp"
DEFAULT_BASE_URL = "http://127.0.0.1:8080"
HTTP_HOST = "127.0.0.1"
HTTP_PORT = 8080
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# Pin Coplay Unity package + Python server to the same major line.
UNITY_PACKAGE_ID = "com.coplaydev.unity-mcp"
UNITY_PACKAGE_VERSION = "10.0.0"
UNITY_PACKAGE_GIT = (
    f"https://github.com/CoplayDev/unity-mcp.git"
    f"?path=/MCPForUnity#v{UNITY_PACKAGE_VERSION}"
)
SERVER_PYPI = f"mcpforunityserver=={UNITY_PACKAGE_VERSION}"
SERVER_ENTRY = "mcp-for-unity"

UV_VERSION = "0.7.16"
UV_RELEASE_BASE = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}"

# Verified sha256 digests for pinned uv release artifacts.
UV_ARTIFACTS: dict[str, dict[str, str]] = {
    "win_amd64": {
        "filename": "uv-x86_64-pc-windows-msvc.zip",
        "sha256": "409d19c14a9b1ce83bf7331dbda89984802efb3a2fbf9ffdf149b22ab9cf2826",
        "archive": "zip",
        "exe": "uv.exe",
    },
    "darwin_arm64": {
        "filename": "uv-aarch64-apple-darwin.tar.gz",
        "sha256": "a157919a2a615fac5de0fcef5120a63de7e6582fb6e0ae4428238af347ed1054",
        "archive": "tar.gz",
        "exe": "uv",
    },
    "darwin_x86_64": {
        "filename": "uv-x86_64-apple-darwin.tar.gz",
        "sha256": "414cb3c348b0482bc88fdabbc267973a11401e684a78fd471b2c4553fa8b6965",
        "archive": "tar.gz",
        "exe": "uv",
    },
    "linux_x86_64": {
        "filename": "uv-x86_64-unknown-linux-gnu.tar.gz",
        "sha256": "c51f5dc9fd33e789992839d2957d6cfe0b6dce1cd7ec641740af456b12e9d468",
        "archive": "tar.gz",
        "exe": "uv",
    },
}

BOOTSTRAP_SCRIPT_NAME = "UefnDuckyUnityMcpBootstrap.cs"
BOOTSTRAP_MARKER = "UefnDuckyUnityMcpBootstrap.applied"

UNITY_INTENT = r"\b(unity|gameobject|prefab|unity\s*mcp)\b"

DESCRIPTION = (
    "Control Unity Editor from Ducky. Runs the Coplay MCP server locally and "
    "installs MCP for Unity into open Hub projects — no setup."
)

WATCH_INTERVAL_S = 5.0
PROBE_TIMEOUT_S = 2.5
DOWNLOAD_TIMEOUT_S = 300
CONNECT_TIMEOUT_S = 12.0
CALL_TIMEOUT_S = 120.0
