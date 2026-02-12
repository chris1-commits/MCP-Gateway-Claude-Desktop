"""
ElevenLabs Webhook Endpoints — MCP Gateway

Routes:
    POST /webhooks/elevenlabs/conversation-initiation
    POST /webhooks/elevenlabs/post-call

Hub-and-spoke compliant: these are DIRECT Gateway termination endpoints.
Replaces n8n bridge workflows:

  - conversation-initiation-webhook (fqa_PcY5k6iUtlOVuBfBt)
  - OH - Post-Call Result Capture (webhook/3f02b114-…)

Auth: HMAC-SHA256 signature verification via ELEVENLABS_WEBHOOK_SECRET.
"""

import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("mcp_gateway.elevenlabs")

router = APIRouter(prefix="/webhooks/elevenlabs", tags=["elevenlabs"])


# ═══════════════════════════════════════════
# Models — Conversation Initiation
# ═══════════════════════════════════════════

class ConversationInitiationRequest(BaseModel):
    """Inbound payload from ElevenLabs before a conversation starts."""

    number: Optional[str] = Field(None, description="Caller phone (Twilio-backed)")
    caller_id: Optional[str] = Field(None, description="Caller ID (native telephony)")
    phone_number: Optional[str] = Field(None, description="Alt phone field")
    from_number: Optional[str] = Field(None, alias="from", description="'from' field")
    agent_id: Optional[str] = None
    conversation_id: Optional[str] = None
    call_sid: Optional[str] = None

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    def resolve_phone(self) -> Optional[str]:
        """Extract caller phone from whichever field is populated."""
        return self.number or self.caller_id or self.phone_number or self.from_number


class DynamicVariables(BaseModel):
    """Dynamic variables returned to ElevenLabs agent. All values must be strings."""

    first_name: str = "there"
    last_name: str = ""
    lead_status: str = "new"
    qualification_score: str = "0"
    property_type: str = "not specified"
    source: str = "phone"
    previous_contact: str = "no"
    last_interaction: str = "first contact"
    notes: str = ""
    ohid: str = ""
    budget_range: str = "not discussed"
    investment_timeline: str = "not discussed"
    preferred_location: str = "Dubai"
    nationality: str = ""
    occupation: str = ""
    phone: str = ""


class ConversationConfigOverride(BaseModel):
    agent: dict = Field(default_factory=lambda: {"language": "en"})


class ConversationInitiationResponse(BaseModel):
    type: str = "conversation_initiation_client_data"
    dynamic_variables: dict[str, str] = Field(default_factory=dict)
    conversation_config_override: Optional[ConversationConfigOverride] = None


# ═══════════════════════════════════════════
# Models — Post-Call
# ═══════════════════════════════════════════

class ConversationAnalysis(BaseModel):
    call_successful: Optional[str] = None
    call_summary: Optional[str] = None
    transcript_summary: Optional[str] = None
    data_collection: Optional[dict[str, Any]] = None
    evaluation_criteria_results: Optional[dict[str, Any]] = None


class PostCallRequest(BaseModel):
    """Inbound payload from ElevenLabs after a conversation ends."""

    conversation_id: str
    agent_id: Optional[str] = None
    status: Optional[str] = None
    call_duration_secs: Optional[float] = None
    call_cost_credits: Optional[float] = None
    call_sid: Optional[str] = None
    phone_number: Optional[str] = None
    transcript: Optional[list[dict[str, Any]]] = None
    analysis: Optional[ConversationAnalysis] = None
    human_transfer: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    collected_data: Optional[dict[str, Any]] = None

    model_config = ConfigDict(extra="allow")


class PostCallResponse(BaseModel):
    received: bool = True
    conversation_id: str
    correlation_id: str
    processed_at: str
    transfer_failure_flagged: bool = False


# ═══════════════════════════════════════════
# Signature Verification
# ═══════════════════════════════════════════

def verify_elevenlabs_signature(
    raw_body: bytes,
    signature: Optional[str],
    secret: Optional[str],
) -> bool:
    """
    Verify HMAC-SHA256 webhook signature.
    Skips verification if ELEVENLABS_WEBHOOK_SECRET is unset (dev mode).
    """
    if not secret:
        logger.warning(
            "ELEVENLABS_WEBHOOK_SECRET not set — skipping signature verification"
        )
        return True
    if not signature:
        return False
    expected = hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


# ═══════════════════════════════════════════
# Lead Lookup (pluggable backend)
# ═══════════════════════════════════════════

# This is the integration seam. In production, replace with:
#   Option A: Direct asyncpg query to lead_context table
#   Option B: Internal call to lookup_ohid MCP tool
#   Option C: HTTP call to n8n Data Table (transitional bridge)
#
# The interface contract is: phone in → dict | None out

_lead_lookup_fn = None


def set_lead_lookup(fn):
    """Register a lead lookup function. fn(phone: str) -> Optional[dict]"""
    global _lead_lookup_fn
    _lead_lookup_fn = fn


async def _lookup_lead(phone: str) -> Optional[dict]:
    """Resolve lead by phone using registered lookup function."""
    if _lead_lookup_fn is None:
        return None
    result = _lead_lookup_fn(phone)
    # Support both sync and async callables
    if hasattr(result, "__await__"):
        return await result
    return result


_post_call_handler_fn = None


def set_post_call_handler(fn):
    """Register a post-call handler. fn(data: dict) -> None"""
    global _post_call_handler_fn
    _post_call_handler_fn = fn


async def _handle_post_call(data: dict) -> None:
    """Persist post-call data using registered handler."""
    if _post_call_handler_fn is None:
        logger.info("No post-call handler registered — data logged only",
                     extra={"keys": list(data.keys())})
        return
    result = _post_call_handler_fn(data)
    if hasattr(result, "__await__"):
        await result


# ═══════════════════════════════════════════
# Variable Mapping
# ═══════════════════════════════════════════

def map_lead_to_variables(lead: dict, phone: str) -> DynamicVariables:
    """Map lead record to ElevenLabs dynamic variables."""
    has_previous = (
        lead.get("Lead_Status", "new") not in ("new", "New", "")
        and lead.get("Lead_Status") is not None
    )
    return DynamicVariables(
        first_name=lead.get("First_Name") or "there",
        last_name=lead.get("Last_Name") or "",
        lead_status=lead.get("Lead_Status") or "new",
        qualification_score=str(lead.get("qualification_score", 0)),
        property_type=lead.get("Lead_Type") or "not specified",
        source=lead.get("Lead_Source") or lead.get("Campaign") or "phone",
        previous_contact="yes" if has_previous else "no",
        last_interaction=(
            lead.get("call_timestamp") or lead.get("Modified_Time") or "first contact"
        ),
        notes=lead.get("call_summary") or lead.get("Description") or "",
        ohid=lead.get("DistributionID") or str(lead.get("Record_Id", "")),
        budget_range=lead.get("Budget_Range") or "not discussed",
        investment_timeline=lead.get("Investment_Timeline") or "not discussed",
        preferred_location=lead.get("Preferred_Location") or "Dubai",
        nationality=lead.get("Nationality") or "",
        occupation=lead.get("Occupation") or "",
        phone=phone,
    )


# ═══════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════

@router.post("/conversation-initiation")
async def conversation_initiation(
    request: Request,
    x_elevenlabs_signature: Optional[str] = Header(None),
):
    """
    Pre-call webhook. Must respond within 5 seconds.
    Returns dynamic_variables for agent personalization.
    """
    correlation_id = str(uuid4())
    start = time.monotonic()

    raw_body = await request.body()
    secret = os.environ.get("ELEVENLABS_WEBHOOK_SECRET")
    if not verify_elevenlabs_signature(raw_body, x_elevenlabs_signature, secret):
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    req = ConversationInitiationRequest(**body)
    phone = req.resolve_phone()

    logger.info("conversation-initiation received",
                extra={"correlation_id": correlation_id, "phone": phone,
                       "agent_id": req.agent_id, "conversation_id": req.conversation_id})

    # Lead lookup
    dynamic_vars = DynamicVariables()
    if phone:
        dynamic_vars.phone = phone
        try:
            lead = await _lookup_lead(phone)
            if lead:
                dynamic_vars = map_lead_to_variables(lead, phone)
                logger.info("Lead resolved", extra={
                    "correlation_id": correlation_id,
                    "lead_status": dynamic_vars.lead_status,
                    "ohid": dynamic_vars.ohid,
                })
        except Exception as e:
            logger.error("Lead lookup failed — defaults used",
                         extra={"correlation_id": correlation_id, "error": str(e)})

    resp = ConversationInitiationResponse(
        dynamic_variables=dynamic_vars.model_dump(),
        conversation_config_override=ConversationConfigOverride(),
    )

    elapsed = (time.monotonic() - start) * 1000
    logger.info("conversation-initiation responded",
                extra={"correlation_id": correlation_id, "elapsed_ms": round(elapsed, 1),
                       "has_lead": dynamic_vars.lead_status != "new"})
    return resp.model_dump()


@router.post("/post-call")
async def post_call(
    request: Request,
    x_elevenlabs_signature: Optional[str] = Header(None),
):
    """
    Post-call webhook. Fire-and-forget from ElevenLabs.
    Processes transcript, analysis, transfer outcome.
    """
    correlation_id = str(uuid4())

    raw_body = await request.body()
    secret = os.environ.get("ELEVENLABS_WEBHOOK_SECRET")
    if not verify_elevenlabs_signature(raw_body, x_elevenlabs_signature, secret):
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    req = PostCallRequest(**body)

    logger.info("post-call received", extra={
        "correlation_id": correlation_id,
        "conversation_id": req.conversation_id,
        "status": req.status,
        "duration": req.call_duration_secs,
        "human_transfer": req.human_transfer,
        "phone": req.phone_number,
    })

    # Extract analysis
    call_summary = ""
    qualification_score = 0
    if req.analysis:
        call_summary = req.analysis.call_summary or req.analysis.transcript_summary or ""
        if req.analysis.data_collection:
            raw_score = req.analysis.data_collection.get("qualification_score")
            if raw_score is not None:
                try:
                    qualification_score = int(raw_score)
                except (ValueError, TypeError):
                    pass

    # Transfer failure detection
    transfer_failure = req.human_transfer == "failure"
    if transfer_failure:
        logger.warning("TRANSFER FAILURE — escalation path needed", extra={
            "correlation_id": correlation_id,
            "conversation_id": req.conversation_id,
            "phone": req.phone_number,
        })

    # Persist
    lead_update = {
        "conversation_id": req.conversation_id,
        "call_sid": req.call_sid,
        "call_status": req.status or "unknown",
        "call_summary": call_summary,
        "call_timestamp": datetime.now(timezone.utc).isoformat(),
        "qualification_score": qualification_score,
        "call_duration_secs": req.call_duration_secs,
        "human_transfer": req.human_transfer,
        "phone": req.phone_number,
        "agent_id": req.agent_id,
        "collected_data": req.collected_data,
        "transfer_failure": transfer_failure,
    }

    try:
        await _handle_post_call(lead_update)
    except Exception as e:
        logger.error("Post-call handler failed",
                     extra={"correlation_id": correlation_id, "error": str(e)})

    return PostCallResponse(
        conversation_id=req.conversation_id,
        correlation_id=correlation_id,
        processed_at=datetime.now(timezone.utc).isoformat(),
        transfer_failure_flagged=transfer_failure,
    ).model_dump()
