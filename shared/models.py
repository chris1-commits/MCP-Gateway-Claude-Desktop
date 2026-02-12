"""
Opulent Horizons — Shared Domain Models
Migrated from FastAPI gateway. These Pydantic models are framework-agnostic
and used across all MCP servers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Dict, Any, Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Core domain models
# ---------------------------------------------------------------------------

class Person(BaseModel):
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None


class LeadDetails(BaseModel):
    budget_range: Optional[str] = None
    location: Optional[str] = None
    property_type: Optional[str] = None
    free_text: Optional[str] = None

class Consent(BaseModel):
    marketing: bool
    source: Optional[str] = None
    timestamp: Optional[datetime] = None


class LeadIngestRequest(BaseModel):
    source_system: str = Field(
        ..., pattern=r"^(META|WEB|TWILIO|ZOHO_SOCIAL|ZOHO_CRM)$"
    )
    source_lead_id: str
    channel: str = Field(
        ..., pattern=r"^(WEB_FORM|META_LEAD_AD|INBOUND_CALL|OUTBOUND_CALL|SOCIAL|CRM)$"
    )
    person: Person
    lead_details: Optional[LeadDetails] = None
    consent: Consent
    raw_payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime
    meta: Dict[str, Any] = Field(default_factory=dict)


class TwilioWebhookPayload(BaseModel):
    """Twilio webhook payload for voice call events."""
    call_sid: str = Field(..., description="Twilio Call SID")
    call_status: str = Field(..., description="Call status (ringing, in-progress, completed, etc.)")
    direction: str = Field(..., description="inbound or outbound-dial")
    from_number: str = Field(alias="From", description="Caller phone number")
    to: str = Field(alias="To", description="Called phone number")
    recording_url: Optional[str] = Field(None, alias="RecordingUrl")
    recording_sid: Optional[str] = Field(None, alias="RecordingSid")
    call_duration: Optional[str] = Field(None, alias="CallDuration")
    raw: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}

# ---------------------------------------------------------------------------
# Zoho CRM models (from zoho_crm_sync tool)
# ---------------------------------------------------------------------------

class ZohoCRMSyncRequest(BaseModel):
    """Request to sync lead between Zoho CRM and Property DB."""
    zoho_lead_id: str = Field(..., description="Zoho CRM lead ID")
    sync_direction: Literal["inbound", "outbound", "bidirectional"] = Field(
        ..., description="inbound (Zoho→PropertyDB), outbound (PropertyDB→Zoho), or bidirectional"
    )
    source: Optional[str] = Field(
        None, description="Lead source attribution (e.g. 'leadchain_meta_ads', 'twilio_call')"
    )
    property_db_lead_id: Optional[str] = Field(
        None, description="Property DB lead ID (required for outbound sync)"
    )

    @field_validator("property_db_lead_id")
    @classmethod
    def validate_property_db_lead_id(cls, v, info):
        direction = info.data.get("sync_direction")
        if direction in ("outbound", "bidirectional") and not v:
            raise ValueError("property_db_lead_id required for outbound/bidirectional sync")
        return v


class ZohoCRMSyncResponse(BaseModel):
    """Response after syncing lead."""
    zoho_lead_id: str
    property_db_lead_id: str
    sync_direction: str
    source: Optional[str] = None
    status: Literal["success", "partial", "failed"]
    inbound_success: Optional[bool] = None
    outbound_success: Optional[bool] = None
    error_message: Optional[str] = None
    execution_time_ms: int