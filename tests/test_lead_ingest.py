"""
Tests for Lead Ingest MCP Server — all 5 tools.

Uses InMemoryRepository (no Postgres required).
Tests are split into two groups:
  - Unit tests: call tool functions directly (no lifespan context needed)
  - Integration tests: use subprocess MCP stdio to test tools needing context

Run: pytest tests/test_lead_ingest.py -v
"""

import json
import hashlib
import hmac as hmac_mod
import os
import subprocess
import sys

import pytest

from servers.lead_ingest import mcp


# ---------------------------------------------------------------------------
# Tool registration tests (no server context needed)
# ---------------------------------------------------------------------------

def test_server_name():
    assert mcp.name == "Opulent Horizons Lead Ingest"


def test_tool_count():
    assert len(mcp._tool_manager._tools) == 5


def test_expected_tools():
    names = {t.name for t in mcp._tool_manager._tools.values()}
    expected = {
        "ingest_lead",
        "process_twilio_event",
        "process_notion_event",
        "lookup_ohid",
        "verify_webhook_signature",
    }
    assert names == expected


# ---------------------------------------------------------------------------
# verify_webhook_signature — sync tool, no context needed
# ---------------------------------------------------------------------------

class TestVerifyWebhookSignature:
    def test_valid_twilio_signature(self):
        secret = "test-secret-123"
        os.environ["TWILIO_AUTH_TOKEN"] = secret
        body = b'{"event":"call.completed"}'
        expected_sig = hmac_mod.new(
            secret.encode(), msg=body, digestmod=hashlib.sha256
        ).hexdigest()

        from servers.lead_ingest import verify_webhook_signature
        result = verify_webhook_signature(
            body_hex=body.hex(),
            signature=expected_sig,
            source="twilio",
        )
        assert result["valid"] is True
        assert result["source"] == "twilio"
        os.environ["TWILIO_AUTH_TOKEN"] = ""

    def test_invalid_signature(self):
        os.environ["TWILIO_AUTH_TOKEN"] = "real-secret"
        from servers.lead_ingest import verify_webhook_signature
        result = verify_webhook_signature(
            body_hex=b"test body".hex(),
            signature="0" * 64,
            source="twilio",
        )
        assert result["valid"] is False
        os.environ["TWILIO_AUTH_TOKEN"] = ""

    def test_valid_notion_signature(self):
        secret = "notion-secret-456"
        os.environ["NOTION_WEBHOOK_SECRET"] = secret
        body = b'{"type":"page.created"}'
        digest = hmac_mod.new(
            secret.encode(), msg=body, digestmod=hashlib.sha256
        ).hexdigest()

        from servers.lead_ingest import verify_webhook_signature
        result = verify_webhook_signature(
            body_hex=body.hex(),
            signature=f"sha256={digest}",
            source="notion",
        )
        assert result["valid"] is True
        assert result["source"] == "notion"
        os.environ["NOTION_WEBHOOK_SECRET"] = ""

    def test_unknown_source(self):
        from servers.lead_ingest import verify_webhook_signature
        result = verify_webhook_signature(
            body_hex=b"test".hex(),
            signature="abc",
            source="unknown_system",
        )
        assert result["valid"] is False
        assert "error" in result

    def test_empty_secret_rejects(self):
        os.environ["TWILIO_AUTH_TOKEN"] = ""
        body = b'{"test":"true"}'
        from servers.lead_ingest import verify_webhook_signature
        result = verify_webhook_signature(
            body_hex=body.hex(),
            signature="anything",
            source="twilio",
        )
        assert result["valid"] is False


# ---------------------------------------------------------------------------
# Integration tests — tools that need lifespan context
# These spawn a subprocess MCP server with stdio transport.
# ---------------------------------------------------------------------------

PYTHON = sys.executable
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mcp_stdio_call(server_module: str, tool_name: str, arguments: dict) -> dict:
    """
    Start an MCP server as a subprocess, send initialize + tool call via stdio,
    return parsed result. Uses Popen to control stdin/stdout timing.
    """
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
        "PGHOST": "",
        "PGDATABASE": "",
        "WORKFLOW_WEBHOOK_URL": "",
        "TWILIO_AUTH_TOKEN": "",
        "NOTION_WEBHOOK_SECRET": "",
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

    # Send messages with small delays to let server process each one
    proc.stdin.write(init_msg + "\n")
    proc.stdin.flush()
    time.sleep(0.5)

    proc.stdin.write(notify_msg + "\n")
    proc.stdin.flush()
    time.sleep(0.3)

    proc.stdin.write(call_msg + "\n")
    proc.stdin.flush()
    time.sleep(3.0)  # Give server time to process tool call

    proc.stdin.close()
    proc.stdin = None  # Prevent communicate() from flushing closed stdin
    stdout, stderr = proc.communicate(timeout=15)

    # Parse newline-delimited JSON responses from stdout
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


class TestIngestLeadIntegration:
    def test_ingest_lead(self):
        result = _mcp_stdio_call("servers.lead_ingest", "ingest_lead", {
            "source_system": "WEB",
            "source_lead_id": "pytest-001",
            "channel": "WEB_FORM",
            "first_name": "Pytest",
            "last_name": "Test",
            "marketing_consent": True,
            "email": "pytest@example.com",
        })
        assert result["status"] == "ingested"
        assert result["source_system"] == "WEB"
        assert "ohid" in result
        assert "ingest_id" in result

    def test_twilio_call_completed(self):
        result = _mcp_stdio_call("servers.lead_ingest", "process_twilio_event", {
            "call_sid": "CA1234567890abcdef1234567890abcdef",
            "call_status": "completed",
            "direction": "inbound",
            "from_number": "+61412345678",
            "to_number": "+61498765432",
            "call_duration": "120",
        })
        assert result["accepted"] is True
        assert result["event_type"] == "CallCompleted"

    def test_twilio_call_ringing(self):
        result = _mcp_stdio_call("servers.lead_ingest", "process_twilio_event", {
            "call_sid": "CA0987654321abcdef0987654321abcdef",
            "call_status": "ringing",
            "direction": "outbound-dial",
            "from_number": "+61498765432",
            "to_number": "+61412345678",
        })
        assert result["accepted"] is True
        assert result["event_type"] == "CallReceived"

    def test_notion_page_created(self):
        result = _mcp_stdio_call("servers.lead_ingest", "process_notion_event", {
            "payload": {
                "type": "page.created",
                "id": "notion-evt-001",
                "data": {"title": "Test Page"},
            },
        })
        assert result["accepted"] is True
        assert result["event_id"] == "notion-evt-001"

    def test_lookup_ohid_not_found(self):
        result = _mcp_stdio_call("servers.lead_ingest", "lookup_ohid", {
            "email": "nonexistent@example.com",
        })
        assert result["found"] is False
