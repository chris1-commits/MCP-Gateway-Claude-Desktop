"""
Shared test fixtures for MCP Gateway tests.

Creates proper MCP client sessions that initialize the server lifespan,
so tools can access ctx.request_context.lifespan_context correctly.
"""

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"
