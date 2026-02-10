"""
Tests for Zoho CRM Sync MCP Server — all 3 tools.

Tests run with empty ZOHO_ACCESS_TOKEN to verify error handling.
Uses subprocess MCP stdio for tools needing lifespan context.
Run: pytest tests/test_zoho_sync.py -v
"""

import json
import os
import subprocess
import sys

import pytest

from servers.zoho_crm_sync import mcp


# ---------------------------------------------------------------------------
# Reuse the stdio helper from lead_ingest tests
# ---------------------------------------------------------------------------

PYTHON = sys.executable
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mcp_stdio_call(server_module: str, tool_name: str, arguments: dict) -> dict:
    """Start MCP server subprocess, send tool call via stdio, return result."""
    import time

    init_msg = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "1.0"},
        },
    })
    notify_msg = json.dumps({
        "jsonrpc": "2.0", "method": "notifications/initialized",
    })
    call_msg = json.dumps({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    })

    env = {
        **os.environ,
        "ZOHO_API_BASE": "https://www.zohoapis.com/crm/v2",
        "ZOHO_ACCESS_TOKEN": "",
        "PROPERTY_DB_HOST": "",
        "PROPERTY_DB_PORT": "5432",
        "PROPERTY_DB_USER": "",
        "PROPERTY_DB_PASSWORD": "",
        "PROPERTY_DB_NAME": "property_db",
    }

    proc = subprocess.Popen(
        [PYTHON, "-m", server_module],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=PROJECT_ROOT,
        env=env,
    )

    proc.stdin.write(init_msg + "\n")
    proc.stdin.flush()
    time.sleep(0.5)

    proc.stdin.write(notify_msg + "\n")
    proc.stdin.flush()
    time.sleep(0.3)

    proc.stdin.write(call_msg + "\n")
    proc.stdin.flush()
    time.sleep(1.5)

    proc.stdin.close()
    stdout, stderr = proc.communicate(timeout=10)

    responses = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            responses.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    for resp in responses:
        if resp.get("id") == 2:
            if "error" in resp:
                return {"error": resp["error"]["message"]}
            result = resp.get("result", {})
            content = result.get("content", [])
            if content and "text" in content[0]:
                return json.loads(content[0]["text"])
            return result

    raise RuntimeError(
        f"No tool response found. responses={responses[:3]}, stderr={stderr[:300]}"
    )


# ---------------------------------------------------------------------------
# Tool registration tests
# ---------------------------------------------------------------------------

def test_server_name():
    assert mcp.name == "Opulent Horizons Zoho CRM Sync"


def test_tool_count():
    assert len(mcp._tool_manager._tools) == 3


def test_expected_tools():
    names = {t.name for t in mcp._tool_manager._tools.values()}
    expected = {"sync_lead", "get_zoho_lead", "upsert_zoho_lead"}
    assert names == expected


# ---------------------------------------------------------------------------
# Integration tests — empty-token guard verification
# ---------------------------------------------------------------------------

class TestZohoEmptyTokenGuards:
    def test_get_zoho_lead_empty_token(self):
        """With no ZOHO_ACCESS_TOKEN, should return clean error."""
        result = _mcp_stdio_call("servers.zoho_crm_sync", "get_zoho_lead", {
            "lead_id": "12345678901234",
        })
        assert result.get("found") is False or "error" in result

    def test_upsert_zoho_lead_empty_token(self):
        """With no ZOHO_ACCESS_TOKEN, should return clean error."""
        result = _mcp_stdio_call("servers.zoho_crm_sync", "upsert_zoho_lead", {
            "last_name": "TestZoho",
            "email": "zoho-test@example.com",
        })
        assert result.get("success") is False or "error" in result

    def test_sync_lead_inbound_empty_token(self):
        """Inbound sync with no token should fail gracefully."""
        result = _mcp_stdio_call("servers.zoho_crm_sync", "sync_lead", {
            "zoho_lead_id": "12345678901234",
            "sync_direction": "inbound",
            "source": "pytest",
        })
        assert result["status"] == "failed"
        assert result.get("inbound_success") is False
