#!/usr/bin/env python3
"""
Live Pipeline Test — mlinvestments.online Contact Form → ElevenLabs → Cal.com

Creates a random test lead (simulating a website contact form submission),
then exercises the full webhook pipeline locally.

Usage:
    # Run full local pipeline test (no live services needed)
    python scripts/test_live_pipeline.py

    # Run against a deployed gateway
    python scripts/test_live_pipeline.py --gateway-url https://<fqdn>

    # Just create the lead via MCP stdio
    python scripts/test_live_pipeline.py --lead-only
"""

import argparse
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

PYTHON = sys.executable
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# Random lead generator (simulates mlinvestments.online contact form)
# ---------------------------------------------------------------------------

FIRST_NAMES = ["Aisha", "Raj", "Fatima", "Oliver", "Mei", "Carlos", "Elena", "James", "Priya", "Aleksandr"]
LAST_NAMES = ["Al-Rashid", "Patel", "Chen", "Williams", "Kowalski", "Nakamura", "Santos", "Müller", "Singh", "Ivanova"]
NATIONALITIES = ["UAE", "British", "Indian", "Chinese", "American", "Australian", "Canadian", "German", "Russian", "Brazilian"]
OCCUPATIONS = ["Investment Banker", "Tech Entrepreneur", "Medical Consultant", "Property Developer",
               "Fund Manager", "Corporate Lawyer", "Senior Executive", "Business Owner"]
LOCATIONS = ["Dubai Marina", "Palm Jumeirah", "Downtown Dubai", "Business Bay",
             "JBR", "Dubai Hills", "Creek Harbour", "Bluewaters Island"]
PROPERTY_TYPES = ["1BR Apartment", "2BR Apartment", "3BR Apartment", "Penthouse",
                  "Studio", "Townhouse", "Villa", "Duplex"]
BUDGETS = ["AED 500,000 - 1,000,000", "AED 1,000,000 - 1,500,000",
           "AED 1,500,000 - 2,500,000", "AED 2,500,000 - 5,000,000",
           "AED 5,000,000+", "£100,000 - £200,000", "£200,000 - £500,000"]
TIMELINES = ["Immediate", "1-3 months", "3-6 months", "6-12 months", "12+ months"]
FREE_TEXTS = [
    "Interested in fractional ownership opportunities for investment portfolio diversification",
    "Looking for a holiday home with rental yield potential in a prime location",
    "Relocating to Dubai, need family-friendly community with good schools nearby",
    "First-time investor, interested in off-plan properties with payment plans",
    "Want to understand ROI for short-term rental properties in tourist areas",
    "Downsizing from villa, looking for luxury apartment with sea view",
    "Corporate relocation, need serviced apartment in business district",
    "Interested in new launches, prefer branded residences with hotel management",
]


def generate_random_lead():
    """Generate a realistic random lead as if from mlinvestments.online contact form."""
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    email = f"{first.lower()}.{last.lower().replace('-', '')}@example.com"
    phone = f"+971{random.choice(['50', '55', '56', '52', '54'])}{random.randint(1000000, 9999999)}"

    return {
        "source_system": "WEB",
        "source_lead_id": f"ml-web-{int(time.time())}-{random.randint(100, 999)}",
        "channel": "WEB_FORM",
        "first_name": first,
        "last_name": last,
        "marketing_consent": True,
        "email": email,
        "phone": phone,
        "budget_range": random.choice(BUDGETS),
        "location": random.choice(LOCATIONS),
        "property_type": random.choice(PROPERTY_TYPES),
        "free_text": random.choice(FREE_TEXTS),
        "consent_source": "mlinvestments.online/contact",
    }


# ---------------------------------------------------------------------------
# MCP stdio helper
# ---------------------------------------------------------------------------

def mcp_call(tool_name: str, arguments: dict) -> dict:
    """Call an MCP tool via subprocess stdio transport."""
    init_msg = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "live-test", "version": "1.0"},
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
        "PGHOST": os.environ.get("PGHOST", ""),
        "PGDATABASE": os.environ.get("PGDATABASE", ""),
        "WORKFLOW_WEBHOOK_URL": os.environ.get("WORKFLOW_WEBHOOK_URL", ""),
        "TWILIO_AUTH_TOKEN": os.environ.get("TWILIO_AUTH_TOKEN", ""),
        "NOTION_WEBHOOK_SECRET": os.environ.get("NOTION_WEBHOOK_SECRET", ""),
        "ELEVENLABS_WEBHOOK_SECRET": os.environ.get("ELEVENLABS_WEBHOOK_SECRET", ""),
        "CALCOM_WEBHOOK_SECRET": os.environ.get("CALCOM_WEBHOOK_SECRET", ""),
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
# Webhook test helper (local FastAPI TestClient)
# ---------------------------------------------------------------------------

def test_webhooks_local(lead: dict, ohid: str):
    """Exercise ElevenLabs webhook endpoints locally via TestClient."""
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
    from app import app
    from elevenlabs_webhooks import set_lead_lookup, set_post_call_handler
    from fastapi.testclient import TestClient

    client = TestClient(app)
    phone = lead["phone"]
    post_call_data = []

    # --- Pre-call: new caller (no lookup) ---
    print("\n--- Step 2a: Pre-call webhook (new caller) ---")
    resp = client.post("/webhooks/elevenlabs/conversation-initiation", json={
        "number": phone,
        "agent_id": "agent_opulent_horizons_v2",
        "conversation_id": f"conv_live_{int(time.time())}",
    })
    assert resp.status_code == 200
    dv = resp.json()["dynamic_variables"]
    print(f"  Phone: {dv['phone']}")
    print(f"  Name: {dv['first_name']} (default — no lookup registered)")
    print(f"  Status: {dv['lead_status']}")
    assert dv["phone"] == phone
    assert dv["first_name"] == "there"  # No lookup yet

    # --- Pre-call: known caller (with lookup) ---
    print("\n--- Step 2b: Pre-call webhook (known caller with lead lookup) ---")

    async def mock_lead_lookup(p):
        if p == phone:
            return {
                "First_Name": lead["first_name"],
                "Last_Name": lead["last_name"],
                "Lead_Status": "new",
                "qualification_score": 0,
                "Lead_Type": lead.get("property_type", ""),
                "Lead_Source": "mlinvestments.online",
                "DistributionID": ohid,
                "Budget_Range": lead.get("budget_range", ""),
                "Investment_Timeline": "not discussed",
                "Preferred_Location": lead.get("location", "Dubai"),
                "Nationality": random.choice(NATIONALITIES),
                "Occupation": random.choice(OCCUPATIONS),
            }
        return None

    set_lead_lookup(mock_lead_lookup)

    conv_id = f"conv_live_{int(time.time())}"
    resp = client.post("/webhooks/elevenlabs/conversation-initiation", json={
        "number": phone,
        "agent_id": "agent_opulent_horizons_v2",
        "conversation_id": conv_id,
    })
    assert resp.status_code == 200
    dv = resp.json()["dynamic_variables"]
    print(f"  Name: {dv['first_name']} {dv['last_name']}")
    print(f"  OHID: {dv['ohid']}")
    print(f"  Property: {dv['property_type']}")
    print(f"  Budget: {dv['budget_range']}")
    print(f"  Location: {dv['preferred_location']}")
    assert dv["first_name"] == lead["first_name"]
    assert dv["ohid"] == ohid

    # --- Post-call ---
    print("\n--- Step 3: Post-call webhook ---")

    async def capture_handler(data):
        post_call_data.append(data)

    set_post_call_handler(capture_handler)

    # Simulate a call conversation
    viewing_date = (datetime.now(timezone.utc) + timedelta(days=random.randint(2, 7))).strftime("%Y-%m-%d")
    resp = client.post("/webhooks/elevenlabs/post-call", json={
        "conversation_id": conv_id,
        "agent_id": "agent_opulent_horizons_v2",
        "status": "done",
        "call_duration_secs": round(random.uniform(60, 300), 1),
        "phone_number": phone,
        "human_transfer": "not_needed",
        "transcript": [
            {"role": "agent", "message": f"Hello {lead['first_name']}, welcome to Opulent Horizons."},
            {"role": "user", "message": "Hi, I submitted an enquiry on your website about properties in Dubai."},
            {"role": "agent", "message": f"Yes, I can see your interest in {lead.get('property_type', 'properties')} in {lead.get('location', 'Dubai')}."},
            {"role": "user", "message": "I'd like to schedule a viewing if possible."},
            {"role": "agent", "message": f"Absolutely. How about {viewing_date} at 10am?"},
            {"role": "user", "message": "That works perfectly."},
        ],
        "analysis": {
            "call_successful": "true",
            "call_summary": (
                f"Website lead {lead['first_name']} {lead['last_name']} called regarding "
                f"{lead.get('property_type', 'property')} in {lead.get('location', 'Dubai')}. "
                f"Viewing scheduled for {viewing_date}."
            ),
            "data_collection": {
                "qualification_score": str(random.randint(40, 90)),
                "preferred_viewing_date": viewing_date,
            },
        },
    })
    assert resp.status_code == 200
    data = resp.json()
    print(f"  Conversation: {data['conversation_id']}")
    print(f"  Transfer failure: {data['transfer_failure_flagged']}")
    assert data["received"] is True
    assert data["transfer_failure_flagged"] is False

    if post_call_data:
        post = post_call_data[0]
        print(f"  Summary: {post['call_summary'][:80]}...")
        print(f"  Score: {post['qualification_score']}")
        print(f"  Duration: {post['call_duration_secs']}s")

    # Cleanup
    set_lead_lookup(None)
    set_post_call_handler(None)

    return conv_id, viewing_date


def test_calcom_booking(lead: dict, conv_id: str, viewing_date: str):
    """Exercise Cal.com booking via MCP tool."""
    print("\n--- Step 4: Cal.com booking confirmation ---")
    booking_id = random.randint(10000, 99999)

    result = mcp_call("process_calcom_event", {
        "trigger_event": "BOOKING_CREATED",
        "booking_id": booking_id,
        "title": f"Property Viewing — {lead.get('property_type', 'Apartment')} {lead.get('location', 'Dubai')}",
        "start_time": f"{viewing_date}T10:00:00+04:00",
        "end_time": f"{viewing_date}T10:30:00+04:00",
        "attendee_name": f"{lead['first_name']} {lead['last_name']}",
        "attendee_email": lead.get("email", ""),
        "attendee_phone": lead.get("phone", ""),
        "organizer_name": "Opulent Horizons Viewings",
        "organizer_email": "viewings@opulenthorizons.com",
        "location": f"Show apartment, {lead.get('location', 'Dubai')}",
        "status": "ACCEPTED",
        "metadata": {
            "conversation_id": conv_id,
            "agent_id": "agent_opulent_horizons_v2",
            "source": "elevenlabs_agent",
        },
    })
    assert result["accepted"] is True
    assert result["event_type"] == "CalcomBookingCreated"
    print(f"  Booking ID: {result['booking_id']}")
    print(f"  Event type: {result['event_type']}")
    print(f"  OHID: {result.get('ohid', 'N/A')}")

    return booking_id


def test_elevenlabs_mcp_event(lead: dict, conv_id: str):
    """Persist call event via MCP tool."""
    print("\n--- Step 5: ElevenLabs MCP event persistence ---")
    result = mcp_call("process_elevenlabs_event", {
        "event_type": "call.ended",
        "agent_id": "agent_opulent_horizons_v2",
        "conversation_id": conv_id,
        "call_duration_secs": random.randint(60, 300),
        "caller_id": lead.get("phone", ""),
        "call_successful": True,
        "transcript": f"Agent assisted {lead['first_name']} with property viewing in {lead.get('location', 'Dubai')}.",
    })
    assert result["accepted"] is True
    assert result["event_type"] == "ElevenLabsCallCompleted"
    print(f"  Event: {result['event_type']}")
    print(f"  Conversation: {result['conversation_id']}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Live pipeline test")
    parser.add_argument("--lead-only", action="store_true",
                        help="Only create the lead, skip webhook tests")
    parser.add_argument("--gateway-url", type=str, default=None,
                        help="Test against deployed gateway URL (not yet implemented)")
    args = parser.parse_args()

    print("=" * 60)
    print("  OPULENT HORIZONS — Live Pipeline Test")
    print("  Source: mlinvestments.online contact form (simulated)")
    print("=" * 60)

    # Step 1: Generate and ingest lead
    lead = generate_random_lead()
    print("\n--- Step 1: Create lead from website contact form ---")
    print(f"  Name: {lead['first_name']} {lead['last_name']}")
    print(f"  Email: {lead['email']}")
    print(f"  Phone: {lead['phone']}")
    print(f"  Property: {lead['property_type']} in {lead['location']}")
    print(f"  Budget: {lead['budget_range']}")
    print(f"  Source: {lead['source_system']}/{lead['channel']}")

    result = mcp_call("ingest_lead", lead)
    assert result["status"] == "ingested"
    ohid = result["ohid"]
    print(f"  --> OHID: {ohid}")
    print(f"  --> Ingest ID: {result['ingest_id']}")
    print(f"  --> Status: {result['status']}")

    if args.lead_only:
        print("\n  Lead created. Skipping webhook tests (--lead-only).")
        return

    # Step 2-3: ElevenLabs webhooks
    conv_id, viewing_date = test_webhooks_local(lead, ohid)

    # Step 4: Cal.com booking
    booking_id = test_calcom_booking(lead, conv_id, viewing_date)

    # Step 5: ElevenLabs MCP event
    test_elevenlabs_mcp_event(lead, conv_id)

    # Summary
    print("\n" + "=" * 60)
    print("  PIPELINE TEST COMPLETE")
    print("=" * 60)
    print(f"  Lead:          {lead['first_name']} {lead['last_name']}")
    print(f"  OHID:          {ohid}")
    print(f"  Phone:         {lead['phone']}")
    print(f"  Conversation:  {conv_id}")
    print(f"  Booking:       {booking_id}")
    print(f"  Viewing Date:  {viewing_date}")
    print(f"  Source:        mlinvestments.online → WEB/WEB_FORM")
    print("=" * 60)


if __name__ == "__main__":
    main()
