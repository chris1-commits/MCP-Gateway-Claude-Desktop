"""
End-to-end tests for Zoho CRM tools with REAL credentials.
Tests token refresh + all 3 Zoho tools against live Zoho CRM API.

Run:  python tests/e2e_zoho_live.py
Requires: ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN in env
"""

import json
import os
import subprocess
import sys
import time

PYTHON = sys.executable
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Use credentials from project config if not already in env
ZOHO_ENV = {
    **os.environ,
    "ZOHO_API_BASE": os.getenv("ZOHO_API_BASE", "https://www.zohoapis.com.au/crm/v2"),
    "ZOHO_TOKEN_URL": os.getenv("ZOHO_TOKEN_URL", "https://accounts.zoho.com.au/oauth/v2/token"),
    "ZOHO_CLIENT_ID": os.getenv("ZOHO_CLIENT_ID", ""),
    "ZOHO_CLIENT_SECRET": os.getenv("ZOHO_CLIENT_SECRET", ""),
    "ZOHO_REFRESH_TOKEN": os.getenv("ZOHO_REFRESH_TOKEN", ""),
    "ZOHO_ACCESS_TOKEN": "",
    "PROPERTY_DB_HOST": "",
    "PROPERTY_DB_PORT": "5432",
    "PROPERTY_DB_USER": "",
    "PROPERTY_DB_PASSWORD": "",
    "PROPERTY_DB_NAME": "property_db",
}


def mcp_call(tool_name: str, arguments: dict) -> dict:
    """Start Zoho MCP server subprocess, send tool call, return result."""
    init_msg = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "e2e-test", "version": "1.0"},
        },
    })
    notify_msg = json.dumps({
        "jsonrpc": "2.0", "method": "notifications/initialized",
    })
    call_msg = json.dumps({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    })

    proc = subprocess.Popen(
        [PYTHON, "-m", "servers.zoho_crm_sync"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=PROJECT_ROOT,
        env=ZOHO_ENV,
    )

    proc.stdin.write(init_msg + "\n")
    proc.stdin.flush()
    time.sleep(1.0)

    proc.stdin.write(notify_msg + "\n")
    proc.stdin.flush()
    time.sleep(0.5)

    proc.stdin.write(call_msg + "\n")
    proc.stdin.flush()
    time.sleep(4.0)  # Extra time for OAuth token refresh + API call

    proc.stdin.close()
    stdout, stderr = proc.communicate(timeout=20)

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            resp = json.loads(line)
            if resp.get("id") == 2:
                if "error" in resp:
                    return {"error": resp["error"]["message"]}
                result = resp.get("result", {})
                content = result.get("content", [])
                if content and "text" in content[0]:
                    return json.loads(content[0]["text"])
                return result
        except json.JSONDecodeError:
            continue

    raise RuntimeError(
        f"No tool response. responses={stdout[:300]}, stderr={stderr[:500]}"
    )


def test_get_zoho_lead():
    """Test fetching a real lead from Zoho CRM."""
    print("\n=== TEST 1: get_zoho_lead (real lead ID) ===")
    result = mcp_call("get_zoho_lead", {"lead_id": "8744000014469001"})
    print(f"  found: {result.get('found')}")
    if result.get("found"):
        lead = result.get("lead", {})
        print(f"  name: {lead.get('Full_Name')}")
        print(f"  email: {lead.get('Email')}")
        print(f"  OHID: {lead.get('OHID')}")
        print("  RESULT: PASS")
        return True
    else:
        print(f"  error: {result.get('error')}")
        print("  RESULT: FAIL")
        return False


def test_upsert_zoho_lead():
    """Test creating/updating a lead in Zoho CRM."""
    print("\n=== TEST 2: upsert_zoho_lead (create test lead) ===")
    result = mcp_call("upsert_zoho_lead", {
        "last_name": "MCP-E2E-Test",
        "first_name": "Automated",
        "email": "mcp-e2e-test@opulenthorizons.co",
        "lead_source": "MCP Gateway E2E Test",
        "source_attribution": "pytest_e2e_live",
    })
    print(f"  success: {result.get('success')}")
    if result.get("success"):
        print(f"  zoho_lead_id: {result.get('zoho_lead_id')}")
        print(f"  action: {result.get('action')}")
        print("  RESULT: PASS")
        return result.get("zoho_lead_id")
    else:
        print(f"  error: {result.get('error')}")
        print("  RESULT: FAIL")
        return None


def test_sync_lead_inbound(lead_id: str):
    """Test inbound sync (Zoho -> PropertyDB) with a real lead."""
    print(f"\n=== TEST 3: sync_lead inbound (lead_id={lead_id}) ===")
    result = mcp_call("sync_lead", {
        "zoho_lead_id": lead_id,
        "sync_direction": "inbound",
        "source": "e2e_test",
    })
    print(f"  status: {result.get('status')}")
    print(f"  inbound_success: {result.get('inbound_success')}")
    print(f"  execution_time_ms: {result.get('execution_time_ms')}")
    if result.get("inbound_success"):
        print("  RESULT: PASS")
        return True
    else:
        print(f"  error: {result.get('error_message')}")
        print("  RESULT: FAIL")
        return False


if __name__ == "__main__":
    print("Opulent Horizons MCP Gateway — Zoho CRM E2E Tests (LIVE)")
    print("=" * 60)

    passed = 0
    failed = 0

    # Test 1: Get existing lead
    if test_get_zoho_lead():
        passed += 1
    else:
        failed += 1

    # Test 2: Upsert a test lead
    new_lead_id = test_upsert_zoho_lead()
    if new_lead_id:
        passed += 1
    else:
        failed += 1

    # Test 3: Inbound sync with real lead
    sync_lead_id = new_lead_id or "8744000014469001"
    if test_sync_lead_inbound(sync_lead_id):
        passed += 1
    else:
        failed += 1

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed, {passed + failed} total")
    sys.exit(0 if failed == 0 else 1)
