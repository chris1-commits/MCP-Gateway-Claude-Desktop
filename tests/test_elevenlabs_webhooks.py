"""
Test suite for ElevenLabs webhook endpoints.
Covers: conversation-initiation, post-call, signature verification,
        lead lookup, error handling, dynamic variable mapping.
"""
import hashlib
import hmac
import json
import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

# Patch env before import
os.environ.pop("ELEVENLABS_WEBHOOK_SECRET", None)

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app import app
from elevenlabs_webhooks import (
    DynamicVariables,
    map_lead_to_variables,
    set_lead_lookup,
    set_post_call_handler,
    verify_elevenlabs_signature,
)

client = TestClient(app)


# ═══════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════

SAMPLE_LEAD = {
    "First_Name": "James",
    "Last_Name": "Wilson",
    "Lead_Status": "contacted",
    "qualification_score": 65,
    "Lead_Type": "2BR apartment",
    "Lead_Source": "Meta Lead Ad",
    "call_timestamp": "2026-02-10T14:30:00Z",
    "call_summary": "Interested in fractional ownership",
    "DistributionID": "OH-12345",
    "Budget_Range": "£150,000 - £200,000",
    "Investment_Timeline": "3-6 months",
    "Preferred_Location": "Dubai Marina",
    "Nationality": "British",
    "Occupation": "Software Engineer",
}


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture(autouse=True)
def _reset_handlers():
    """Reset pluggable handlers between tests."""
    set_lead_lookup(None)
    set_post_call_handler(None)
    os.environ.pop("ELEVENLABS_WEBHOOK_SECRET", None)
    yield
    set_lead_lookup(None)
    set_post_call_handler(None)
    os.environ.pop("ELEVENLABS_WEBHOOK_SECRET", None)


# ═══════════════════════════════════════════
# Health check
# ═══════════════════════════════════════════


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ═══════════════════════════════════════════
# Conversation Initiation — Happy Path
# ═══════════════════════════════════════════


def test_conversation_initiation_new_caller():
    """New caller with no lead data → returns defaults."""
    payload = {"number": "+447700900123", "agent_id": "agent_test"}
    resp = client.post("/webhooks/elevenlabs/conversation-initiation",
                       json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "conversation_initiation_client_data"
    assert data["dynamic_variables"]["first_name"] == "there"
    assert data["dynamic_variables"]["lead_status"] == "new"
    assert data["dynamic_variables"]["phone"] == "+447700900123"


def test_conversation_initiation_known_caller():
    """Known caller → returns populated dynamic variables."""
    async def mock_lookup(phone):
        return SAMPLE_LEAD

    set_lead_lookup(mock_lookup)
    payload = {"number": "+447700900123", "agent_id": "agent_test"}
    resp = client.post("/webhooks/elevenlabs/conversation-initiation",
                       json=payload)
    assert resp.status_code == 200
    dv = resp.json()["dynamic_variables"]
    assert dv["first_name"] == "James"
    assert dv["last_name"] == "Wilson"
    assert dv["lead_status"] == "contacted"
    assert dv["qualification_score"] == "65"
    assert dv["property_type"] == "2BR apartment"
    assert dv["budget_range"] == "£150,000 - £200,000"
    assert dv["previous_contact"] == "yes"
    assert dv["ohid"] == "OH-12345"


def test_conversation_initiation_no_phone():
    """No phone in any field → returns defaults, no lookup attempted."""
    payload = {"agent_id": "agent_test"}
    resp = client.post("/webhooks/elevenlabs/conversation-initiation",
                       json=payload)
    assert resp.status_code == 200
    dv = resp.json()["dynamic_variables"]
    assert dv["first_name"] == "there"
    assert dv["phone"] == ""


def test_conversation_initiation_caller_id_field():
    """Phone in 'caller_id' field (native telephony) → resolved correctly."""
    payload = {"caller_id": "+61400123456", "agent_id": "agent_test"}
    resp = client.post("/webhooks/elevenlabs/conversation-initiation",
                       json=payload)
    assert resp.status_code == 200
    assert resp.json()["dynamic_variables"]["phone"] == "+61400123456"


def test_conversation_initiation_lookup_failure_graceful():
    """Lead lookup raises exception → returns defaults, doesn't crash."""
    async def failing_lookup(phone):
        raise ConnectionError("DB down")

    set_lead_lookup(failing_lookup)
    payload = {"number": "+447700900123"}
    resp = client.post("/webhooks/elevenlabs/conversation-initiation",
                       json=payload)
    assert resp.status_code == 200
    assert resp.json()["dynamic_variables"]["first_name"] == "there"


def test_conversation_initiation_extra_fields_accepted():
    """Unknown fields from ElevenLabs don't cause validation errors."""
    payload = {
        "number": "+447700900123",
        "some_future_field": "value",
        "nested": {"data": True},
    }
    resp = client.post("/webhooks/elevenlabs/conversation-initiation",
                       json=payload)
    assert resp.status_code == 200


# ═══════════════════════════════════════════
# Post-Call — Happy Path
# ═══════════════════════════════════════════


def test_post_call_basic():
    """Standard post-call payload → 200 with conversation_id echo."""
    payload = {
        "conversation_id": "conv_123",
        "status": "done",
        "call_duration_secs": 120.5,
        "phone_number": "+447700900123",
    }
    resp = client.post("/webhooks/elevenlabs/post-call", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["received"] is True
    assert data["conversation_id"] == "conv_123"
    assert data["transfer_failure_flagged"] is False


def test_post_call_with_analysis():
    """Post-call with analysis → extracts summary and score."""
    handler_calls = []

    async def capture_handler(data):
        handler_calls.append(data)

    set_post_call_handler(capture_handler)
    payload = {
        "conversation_id": "conv_456",
        "status": "done",
        "analysis": {
            "call_summary": "Caller interested in 2BR Dubai Marina",
            "data_collection": {"qualification_score": "72"},
        },
    }
    resp = client.post("/webhooks/elevenlabs/post-call", json=payload)
    assert resp.status_code == 200
    assert len(handler_calls) == 1
    assert handler_calls[0]["call_summary"] == "Caller interested in 2BR Dubai Marina"
    assert handler_calls[0]["qualification_score"] == 72


def test_post_call_transfer_failure():
    """Transfer failure → flagged in response and logged."""
    payload = {
        "conversation_id": "conv_789",
        "human_transfer": "failure",
        "phone_number": "+447700900123",
    }
    resp = client.post("/webhooks/elevenlabs/post-call", json=payload)
    assert resp.status_code == 200
    assert resp.json()["transfer_failure_flagged"] is True


def test_post_call_handler_failure_graceful():
    """Post-call handler raises → 200 still returned (fire-and-forget)."""
    async def failing_handler(data):
        raise RuntimeError("CRM down")

    set_post_call_handler(failing_handler)
    payload = {"conversation_id": "conv_err", "status": "done"}
    resp = client.post("/webhooks/elevenlabs/post-call", json=payload)
    assert resp.status_code == 200


# ═══════════════════════════════════════════
# Signature Verification
# ═══════════════════════════════════════════


def test_signature_valid():
    """Valid HMAC signature → request accepted."""
    secret = "test_secret_key_12345"
    os.environ["ELEVENLABS_WEBHOOK_SECRET"] = secret
    payload = json.dumps({"conversation_id": "conv_sig"}).encode()
    sig = _sign(payload, secret)
    resp = client.post(
        "/webhooks/elevenlabs/post-call",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-ElevenLabs-Signature": sig,
        },
    )
    assert resp.status_code == 200


def test_signature_invalid_rejected():
    """Invalid signature → 403."""
    os.environ["ELEVENLABS_WEBHOOK_SECRET"] = "real_secret"
    payload = json.dumps({"conversation_id": "conv_bad"}).encode()
    resp = client.post(
        "/webhooks/elevenlabs/post-call",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-ElevenLabs-Signature": "bad_signature_value",
        },
    )
    assert resp.status_code == 403


def test_signature_missing_rejected():
    """No signature header with secret set → 403."""
    os.environ["ELEVENLABS_WEBHOOK_SECRET"] = "real_secret"
    payload = {"conversation_id": "conv_no_sig"}
    resp = client.post("/webhooks/elevenlabs/post-call", json=payload)
    assert resp.status_code == 403


def test_signature_skipped_no_secret():
    """No ELEVENLABS_WEBHOOK_SECRET → verification skipped (dev mode)."""
    payload = {"conversation_id": "conv_dev"}
    resp = client.post("/webhooks/elevenlabs/post-call", json=payload)
    assert resp.status_code == 200


# ═══════════════════════════════════════════
# Variable Mapping
# ═══════════════════════════════════════════


def test_map_lead_to_variables_full():
    """Full lead record maps correctly."""
    dv = map_lead_to_variables(SAMPLE_LEAD, "+447700900123")
    assert dv.first_name == "James"
    assert dv.previous_contact == "yes"
    assert dv.budget_range == "£150,000 - £200,000"
    assert dv.phone == "+447700900123"


def test_map_lead_to_variables_sparse():
    """Sparse lead record → defaults for missing fields."""
    sparse = {"First_Name": "Sarah", "Lead_Status": "new"}
    dv = map_lead_to_variables(sparse, "+440000000000")
    assert dv.first_name == "Sarah"
    assert dv.previous_contact == "no"
    assert dv.budget_range == "not discussed"
    assert dv.ohid == ""
