"""
End-to-end integration test: Zoho Lead → ElevenLabs Call → Cal.com Booking

Simulates the full workflow locally using InMemoryRepository:
  1. Ingest a lead via MCP tool (simulating Zoho CRM outbound sync)
  2. ElevenLabs conversation-initiation webhook (pre-call lead lookup)
  3. ElevenLabs post-call webhook (transcript + analysis persistence)
  4. Cal.com booking confirmation webhook (OHID resolution from attendee)

No live services required — validates data flow through the gateway.

Run:  python -m pytest tests/e2e_elevenlabs_calcom_flow.py -v
"""

import json
import os
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# MCP stdio helper (for lead ingest + Cal.com tools)
# ---------------------------------------------------------------------------

PYTHON = sys.executable
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mcp_call(tool_name: str, arguments: dict) -> dict:
    """Call an MCP tool via subprocess stdio transport."""
    init_msg = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "e2e-flow", "version": "1.0"},
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
        "ELEVENLABS_WEBHOOK_SECRET": "",
        "CALCOM_WEBHOOK_SECRET": "",
    }

    proc = subprocess.Popen(
        [PYTHON, "-m", "servers.lead_ingest"],
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
    proc.stdin = None
    stdout, stderr = proc.communicate(timeout=15)

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
        f"No tool response. stdout={stdout[:300]}, stderr={stderr[:300]}"
    )


# ---------------------------------------------------------------------------
# ElevenLabs webhook helper (FastAPI TestClient)
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
from app import app
from elevenlabs_webhooks import set_lead_lookup, set_post_call_handler

client = TestClient(app)

# Store post-call data for verification
_post_call_captures = []


@pytest.fixture(autouse=True)
def _reset():
    """Reset handlers and captures between tests."""
    _post_call_captures.clear()
    set_lead_lookup(None)
    set_post_call_handler(None)
    os.environ.pop("ELEVENLABS_WEBHOOK_SECRET", None)
    yield
    set_lead_lookup(None)
    set_post_call_handler(None)
    os.environ.pop("ELEVENLABS_WEBHOOK_SECRET", None)


# ═══════════════════════════════════════════
# Step 1: Lead ingested via MCP (simulates Zoho sync output)
# ═══════════════════════════════════════════

def test_step1_ingest_lead():
    """Simulate a lead arriving from Zoho CRM sync into the pipeline."""
    result = _mcp_call("ingest_lead", {
        "source_system": "ZOHO_CRM",
        "source_lead_id": "8744000014469001",
        "channel": "CRM",
        "first_name": "Sarah",
        "last_name": "Thompson",
        "marketing_consent": True,
        "email": "sarah.thompson@example.com",
        "phone": "+971501234567",
        "budget_range": "AED 1,500,000 - 2,000,000",
        "location": "Dubai Marina",
        "property_type": "2BR Apartment",
        "free_text": "Interested in fractional ownership, investment timeline 6 months",
    })
    assert result["status"] == "ingested"
    assert result["source_system"] == "ZOHO_CRM"
    assert "ohid" in result
    print(f"  Lead ingested: OHID={result['ohid']}")


# ═══════════════════════════════════════════
# Step 2: ElevenLabs conversation-initiation (pre-call lookup)
# ═══════════════════════════════════════════

def test_step2_elevenlabs_precall_new_caller():
    """ElevenLabs pre-call webhook for a new caller — returns defaults."""
    resp = client.post("/webhooks/elevenlabs/conversation-initiation", json={
        "number": "+971501234567",
        "agent_id": "agent_opulent_horizons_v2",
        "conversation_id": "conv_e2e_001",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "conversation_initiation_client_data"

    dv = data["dynamic_variables"]
    assert len(dv) == 16, f"Expected 16 dynamic variables, got {len(dv)}"
    assert dv["phone"] == "+971501234567"
    # No lead lookup registered, so defaults
    assert dv["first_name"] == "there"
    assert dv["lead_status"] == "new"
    print(f"  Pre-call response: {len(dv)} dynamic vars, phone={dv['phone']}")


def test_step2b_elevenlabs_precall_known_caller():
    """ElevenLabs pre-call webhook with lead lookup — returns personalised data."""
    # Simulate what the production wiring does: register a lead lookup
    async def mock_zoho_lookup(phone):
        if phone == "+971501234567":
            return {
                "First_Name": "Sarah",
                "Last_Name": "Thompson",
                "Lead_Status": "contacted",
                "qualification_score": 72,
                "Lead_Type": "2BR Apartment",
                "Lead_Source": "Zoho CRM",
                "DistributionID": "OH-E2E-001",
                "Budget_Range": "AED 1,500,000 - 2,000,000",
                "Investment_Timeline": "6 months",
                "Preferred_Location": "Dubai Marina",
                "Nationality": "British",
                "Occupation": "Investment Banker",
                "call_timestamp": "2026-02-12T09:00:00Z",
                "call_summary": "Expressed interest in fractional ownership",
            }
        return None

    set_lead_lookup(mock_zoho_lookup)

    resp = client.post("/webhooks/elevenlabs/conversation-initiation", json={
        "number": "+971501234567",
        "agent_id": "agent_opulent_horizons_v2",
    })
    assert resp.status_code == 200
    dv = resp.json()["dynamic_variables"]
    assert dv["first_name"] == "Sarah"
    assert dv["last_name"] == "Thompson"
    assert dv["lead_status"] == "contacted"
    assert dv["qualification_score"] == "72"
    assert dv["property_type"] == "2BR Apartment"
    assert dv["budget_range"] == "AED 1,500,000 - 2,000,000"
    assert dv["previous_contact"] == "yes"
    assert dv["ohid"] == "OH-E2E-001"
    assert dv["preferred_location"] == "Dubai Marina"
    assert dv["nationality"] == "British"
    print(f"  Pre-call personalised: {dv['first_name']} {dv['last_name']} "
          f"(OHID={dv['ohid']}, score={dv['qualification_score']})")


# ═══════════════════════════════════════════
# Step 3: ElevenLabs post-call (transcript + analysis)
# ═══════════════════════════════════════════

def test_step3_elevenlabs_postcall():
    """ElevenLabs post-call webhook — processes transcript and analysis."""
    captured = []

    async def capture_handler(data):
        captured.append(data)

    set_post_call_handler(capture_handler)

    resp = client.post("/webhooks/elevenlabs/post-call", json={
        "conversation_id": "conv_e2e_001",
        "agent_id": "agent_opulent_horizons_v2",
        "status": "done",
        "call_duration_secs": 245.3,
        "call_sid": "CA_e2e_test_001",
        "phone_number": "+971501234567",
        "human_transfer": "not_needed",
        "transcript": [
            {"role": "agent", "message": "Welcome back to Opulent Horizons, Sarah."},
            {"role": "user", "message": "Hi, I'd like to schedule a property viewing."},
            {"role": "agent", "message": "I can help with that. When would be convenient?"},
            {"role": "user", "message": "Next Saturday at 10am would be perfect."},
            {"role": "agent", "message": "I'll arrange a viewing for Saturday at 10am."},
        ],
        "analysis": {
            "call_successful": "true",
            "call_summary": "Returning lead Sarah Thompson requested property viewing "
                            "for 2BR apartment in Dubai Marina. Scheduled for Saturday 10am.",
            "data_collection": {
                "qualification_score": "85",
                "preferred_viewing_date": "2026-02-21",
                "preferred_viewing_time": "10:00",
            },
        },
        "collected_data": {
            "viewing_date": "2026-02-21",
            "viewing_time": "10:00",
            "property_interest": "2BR Dubai Marina",
        },
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["received"] is True
    assert data["conversation_id"] == "conv_e2e_001"
    assert data["transfer_failure_flagged"] is False

    # Verify the handler received processed data
    assert len(captured) == 1
    post = captured[0]
    assert post["conversation_id"] == "conv_e2e_001"
    assert post["call_summary"] == (
        "Returning lead Sarah Thompson requested property viewing "
        "for 2BR apartment in Dubai Marina. Scheduled for Saturday 10am."
    )
    assert post["qualification_score"] == 85
    assert post["call_duration_secs"] == 245.3
    assert post["phone"] == "+971501234567"
    print(f"  Post-call processed: conv={post['conversation_id']}, "
          f"score={post['qualification_score']}, duration={post['call_duration_secs']}s")


def test_step3b_elevenlabs_postcall_transfer_failure():
    """Post-call with human transfer failure — flagged for escalation."""
    resp = client.post("/webhooks/elevenlabs/post-call", json={
        "conversation_id": "conv_e2e_002",
        "status": "done",
        "human_transfer": "failure",
        "phone_number": "+971509876543",
        "call_duration_secs": 90.0,
    })
    assert resp.status_code == 200
    assert resp.json()["transfer_failure_flagged"] is True
    print("  Transfer failure flagged for escalation")


# ═══════════════════════════════════════════
# Step 4: Cal.com booking confirmation (post-call action)
# ═══════════════════════════════════════════

def test_step4_calcom_booking_created():
    """Cal.com booking webhook — confirms the viewing scheduled by the agent."""
    result = _mcp_call("process_calcom_event", {
        "trigger_event": "BOOKING_CREATED",
        "booking_id": 98765,
        "title": "Property Viewing — 2BR Dubai Marina Apartment",
        "start_time": "2026-02-21T10:00:00+04:00",
        "end_time": "2026-02-21T10:30:00+04:00",
        "attendee_name": "Sarah Thompson",
        "attendee_email": "sarah.thompson@example.com",
        "attendee_phone": "+971501234567",
        "organizer_name": "Opulent Horizons Viewings",
        "organizer_email": "viewings@opulenthorizons.com",
        "location": "Marina Gate Tower 1, Dubai Marina",
        "status": "ACCEPTED",
        "metadata": {
            "conversation_id": "conv_e2e_001",
            "agent_id": "agent_opulent_horizons_v2",
            "source": "elevenlabs_agent",
        },
    })
    assert result["accepted"] is True
    assert result["event_type"] == "CalcomBookingCreated"
    assert result["booking_id"] == 98765
    print(f"  Booking created: id={result['booking_id']}, "
          f"type={result['event_type']}, ohid={result.get('ohid')}")


def test_step4b_calcom_booking_rescheduled():
    """Cal.com reschedule webhook — attendee changes viewing time."""
    result = _mcp_call("process_calcom_event", {
        "trigger_event": "BOOKING_RESCHEDULED",
        "booking_id": 98765,
        "title": "Property Viewing — 2BR Dubai Marina Apartment",
        "start_time": "2026-02-22T14:00:00+04:00",
        "end_time": "2026-02-22T14:30:00+04:00",
        "attendee_name": "Sarah Thompson",
        "attendee_email": "sarah.thompson@example.com",
        "reschedule_reason": "Work conflict, moved to Sunday afternoon",
        "status": "ACCEPTED",
    })
    assert result["accepted"] is True
    assert result["event_type"] == "CalcomBookingRescheduled"
    print(f"  Booking rescheduled: {result['event_type']}")


def test_step4c_calcom_meeting_ended():
    """Cal.com meeting-ended webhook — viewing completed."""
    result = _mcp_call("process_calcom_event", {
        "trigger_event": "MEETING_ENDED",
        "booking_id": 98765,
        "title": "Property Viewing — 2BR Dubai Marina Apartment",
        "attendee_name": "Sarah Thompson",
        "attendee_email": "sarah.thompson@example.com",
    })
    assert result["accepted"] is True
    assert result["event_type"] == "CalcomMeetingEnded"
    print(f"  Meeting ended: {result['event_type']}")


# ═══════════════════════════════════════════
# Step 5: ElevenLabs MCP tool (event persistence)
# ═══════════════════════════════════════════

def test_step5_elevenlabs_mcp_event():
    """ElevenLabs MCP tool — persists call event as workflow event."""
    result = _mcp_call("process_elevenlabs_event", {
        "event_type": "call.ended",
        "agent_id": "agent_opulent_horizons_v2",
        "conversation_id": "conv_e2e_001",
        "call_duration_secs": 245,
        "caller_id": "+971501234567",
        "call_successful": True,
        "transcript": "Agent helped schedule a property viewing in Dubai Marina.",
    })
    assert result["accepted"] is True
    assert result["event_type"] == "ElevenLabsCallCompleted"
    assert result["conversation_id"] == "conv_e2e_001"
    print(f"  MCP event persisted: {result['event_type']} "
          f"conv={result['conversation_id']}")
