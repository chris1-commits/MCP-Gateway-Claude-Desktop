#!/usr/bin/env python3
"""
Live test: Create a lead for chris@flitetech.com.au from mlinvestments.online
contact form, then run through ElevenLabs pre/post-call and Cal.com booking.

Usage:
    python scripts/test_chris_lead.py
"""

import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

PYTHON = sys.executable
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def mcp_call(tool_name: str, arguments: dict) -> dict:
    """Call an MCP tool via subprocess stdio transport."""
    init_msg = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "chris-test", "version": "1.0"},
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
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=PROJECT_ROOT, env=env,
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

    raise RuntimeError(f"No tool response. stdout={stdout[:300]}, stderr={stderr[:300]}")


def main():
    print("=" * 65)
    print("  TEST: chris@flitetech.com.au — mlinvestments.online lead")
    print("=" * 65)

    # ── Step 1: Ingest lead ──
    lead = {
        "source_system": "WEB",
        "source_lead_id": f"ml-web-chris-{int(time.time())}",
        "channel": "WEB_FORM",
        "first_name": "Chris",
        "last_name": "ML",
        "marketing_consent": True,
        "email": "chris@flitetech.com.au",
        "phone": "+61400000000",
        "budget_range": "AED 2,500,000 - 5,000,000",
        "location": "Dubai Marina",
        "property_type": "2BR Apartment",
        "free_text": "Interested in fractional ownership, high-yield investment properties in premium Dubai locations.",
        "consent_source": "mlinvestments.online/contact",
    }

    print("\n── Step 1: Ingest lead from website contact form ──")
    print(f"  Name:     {lead['first_name']} {lead['last_name']}")
    print(f"  Email:    {lead['email']}")
    print(f"  Phone:    {lead['phone']}")
    print(f"  Property: {lead['property_type']} in {lead['location']}")
    print(f"  Budget:   {lead['budget_range']}")

    result = mcp_call("ingest_lead", lead)
    assert result["status"] == "ingested", f"Ingest failed: {result}"
    ohid = result["ohid"]
    print(f"  ✓ OHID:      {ohid}")
    print(f"  ✓ Ingest ID: {result['ingest_id']}")

    # ── Step 2: ElevenLabs pre-call (personalised) ──
    print("\n── Step 2: ElevenLabs pre-call webhook (personalised) ──")
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
    from app import app
    from elevenlabs_webhooks import set_lead_lookup, set_post_call_handler
    from fastapi.testclient import TestClient

    client = TestClient(app)

    async def lead_lookup(phone):
        if phone == "+61400000000":
            return {
                "First_Name": "Chris",
                "Last_Name": "ML",
                "Lead_Status": "new",
                "qualification_score": 0,
                "Lead_Type": "2BR Apartment",
                "Lead_Source": "mlinvestments.online",
                "DistributionID": ohid,
                "Budget_Range": "AED 2,500,000 - 5,000,000",
                "Investment_Timeline": "3-6 months",
                "Preferred_Location": "Dubai Marina",
                "Nationality": "Australian",
                "Occupation": "Tech Founder",
            }
        return None

    set_lead_lookup(lead_lookup)

    conv_id = f"conv_chris_{int(time.time())}"
    resp = client.post("/webhooks/elevenlabs/conversation-initiation", json={
        "number": "+61400000000",
        "agent_id": "agent_opulent_horizons_v2",
        "conversation_id": conv_id,
    })
    assert resp.status_code == 200
    dv = resp.json()["dynamic_variables"]
    print(f"  ✓ Name:     {dv['first_name']} {dv['last_name']}")
    print(f"  ✓ OHID:     {dv['ohid']}")
    print(f"  ✓ Property: {dv['property_type']}")
    print(f"  ✓ Budget:   {dv['budget_range']}")
    print(f"  ✓ Location: {dv['preferred_location']}")
    print(f"  ✓ Status:   {dv['lead_status']}")

    # ── Step 3: ElevenLabs post-call ──
    print("\n── Step 3: ElevenLabs post-call webhook ──")
    post_call_data = []

    async def capture(data):
        post_call_data.append(data)

    set_post_call_handler(capture)

    viewing_date = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d")
    resp = client.post("/webhooks/elevenlabs/post-call", json={
        "conversation_id": conv_id,
        "agent_id": "agent_opulent_horizons_v2",
        "status": "done",
        "call_duration_secs": 187.4,
        "phone_number": "+61400000000",
        "human_transfer": "not_needed",
        "transcript": [
            {"role": "agent", "message": "Hello Chris, welcome to Opulent Horizons. I understand you've been looking at our Dubai Marina properties."},
            {"role": "user", "message": "Yes, I submitted an enquiry on mlinvestments.online. I'm particularly interested in 2-bedroom apartments with good rental yield."},
            {"role": "agent", "message": "Excellent choice. Dubai Marina 2-beds are achieving 7-9% gross yields. Your budget of AED 2.5-5M gives you access to premium towers. Shall I arrange a viewing?"},
            {"role": "user", "message": "Absolutely. I'll be in Dubai next week. Can we do something on the 15th?"},
            {"role": "agent", "message": f"Perfect. I'll set up a viewing for {viewing_date} at 11am at Marina Gate Tower 1. I'll send a calendar invite to chris@flitetech.com.au."},
            {"role": "user", "message": "That works. Looking forward to it."},
        ],
        "analysis": {
            "call_successful": "true",
            "call_summary": (
                f"Website lead Chris ML from mlinvestments.online enquired about 2BR apartments "
                f"in Dubai Marina with AED 2.5-5M budget. Strong investment intent with focus on "
                f"rental yield (7-9% gross). Viewing scheduled for {viewing_date} at Marina Gate Tower 1. "
                f"Lead is Australian tech founder — high qualification potential."
            ),
            "data_collection": {
                "qualification_score": "82",
                "preferred_viewing_date": viewing_date,
                "preferred_viewing_time": "11:00",
                "investment_focus": "rental_yield",
            },
        },
    })
    assert resp.status_code == 200
    data = resp.json()
    print(f"  ✓ Conversation: {data['conversation_id']}")
    print(f"  ✓ Transfer failure: {data['transfer_failure_flagged']}")
    if post_call_data:
        post = post_call_data[0]
        print(f"  ✓ Score:    {post['qualification_score']}")
        print(f"  ✓ Duration: {post['call_duration_secs']}s")
        print(f"  ✓ Summary:  {post['call_summary'][:80]}...")

    set_lead_lookup(None)
    set_post_call_handler(None)

    # ── Step 4: Cal.com booking ──
    print(f"\n── Step 4: Cal.com booking — {viewing_date} at 11:00 ──")
    booking_id = random.randint(10000, 99999)

    result = mcp_call("process_calcom_event", {
        "trigger_event": "BOOKING_CREATED",
        "booking_id": booking_id,
        "title": "Property Viewing — 2BR Dubai Marina Apartment",
        "start_time": f"{viewing_date}T11:00:00+04:00",
        "end_time": f"{viewing_date}T11:30:00+04:00",
        "attendee_name": "Chris ML",
        "attendee_email": "chris@flitetech.com.au",
        "attendee_phone": "+61400000000",
        "organizer_name": "Opulent Horizons Viewings",
        "organizer_email": "viewings@opulenthorizons.com",
        "location": "Marina Gate Tower 1, Dubai Marina",
        "status": "ACCEPTED",
        "metadata": {
            "conversation_id": conv_id,
            "agent_id": "agent_opulent_horizons_v2",
            "source": "elevenlabs_agent",
            "ohid": ohid,
        },
    })
    assert result["accepted"] is True
    assert result["event_type"] == "CalcomBookingCreated"
    print(f"  ✓ Booking ID: {result['booking_id']}")
    print(f"  ✓ Event type: {result['event_type']}")

    # ── Step 5: ElevenLabs MCP event ──
    print("\n── Step 5: ElevenLabs MCP event persistence ──")
    result = mcp_call("process_elevenlabs_event", {
        "event_type": "call.ended",
        "agent_id": "agent_opulent_horizons_v2",
        "conversation_id": conv_id,
        "call_duration_secs": 187,
        "caller_id": "+61400000000",
        "call_successful": True,
        "transcript": "Agent assisted Chris with property viewing in Dubai Marina. Viewing scheduled.",
    })
    assert result["accepted"] is True
    print(f"  ✓ Event: {result['event_type']}")
    print(f"  ✓ Conv:  {result['conversation_id']}")

    # ── Summary ──
    print("\n" + "=" * 65)
    print("  PIPELINE TEST COMPLETE — chris@flitetech.com.au")
    print("=" * 65)
    print(f"  Lead:          Chris ML (chris@flitetech.com.au)")
    print(f"  OHID:          {ohid}")
    print(f"  Conversation:  {conv_id}")
    print(f"  Booking:       {booking_id}")
    print(f"  Viewing:       {viewing_date} 11:00 @ Marina Gate Tower 1")
    print(f"  Score:         82")
    print(f"  Source:        mlinvestments.online → WEB/WEB_FORM")
    print("=" * 65)

    # ── Cal.com live booking curl ──
    print("\n── To create a REAL Cal.com booking, run this from your machine: ──")
    print(f"""
curl -X POST "https://api.cal.com/v2/bookings" \\
  -H "Authorization: Bearer cal_live_c7f50f2e3f4ab400fee1238bdc160280" \\
  -H "cal-api-version: 2024-08-13" \\
  -H "Content-Type: application/json" \\
  -d '{{
    "start": "{viewing_date}T11:00:00+04:00",
    "eventTypeId": <YOUR_EVENT_TYPE_ID>,
    "attendee": {{
      "name": "Chris ML",
      "email": "chris@flitetech.com.au",
      "timeZone": "Asia/Dubai"
    }},
    "metadata": {{
      "ohid": "{ohid}",
      "conversation_id": "{conv_id}",
      "source": "elevenlabs_agent"
    }}
  }}'
""")
    print("  NOTE: Replace <YOUR_EVENT_TYPE_ID> with your Cal.com event type.")
    print("  To list event types: curl -s https://api.cal.com/v2/event-types \\")
    print('    -H "Authorization: Bearer cal_live_c7f50f2e3f4ab400fee1238bdc160280" \\')
    print('    -H "cal-api-version: 2024-08-13" | python3 -m json.tool')


if __name__ == "__main__":
    main()
