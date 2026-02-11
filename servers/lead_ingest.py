"""
Opulent Horizons — Lead Ingest MCP Server
==========================================
Official MCP Python SDK (FastMCP) implementation.

Exposes lead ingestion, OHID resolution, and workflow event tools
to any MCP client (Claude Desktop, Claude Code, custom agents).

Run:
    # stdio (for Claude Desktop / Claude Code)
    python -m servers.lead_ingest

    # Streamable HTTP (for remote/production)
    python -m servers.lead_ingest --transport streamable-http --port 8001
"""

# NOTE: Do NOT use 'from __future__ import annotations' here.
# The MCP SDK introspects tool function signatures at runtime via
# inspect.signature() to auto-generate JSON schemas. PEP 563 turns
# all annotations into strings, breaking Optional[str] -> schema resolution.

import os
import json
import hmac
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import httpx
from mcp.server.fastmcp import FastMCP, Context

from shared.models import (
    Person, LeadDetails, Consent, LeadIngestRequest, CloudtalkWebhookPayload,
)
from shared.repository import (
    Repository, PostgresRepository, InMemoryRepository, resolve_ohid,
)
from shared.middleware import wrap_tool_with_logging


# ---------------------------------------------------------------------------
# Application context (replaces FastAPI Depends injection)
# ---------------------------------------------------------------------------

@dataclass
class AppContext:
    repo: Repository
    http_client: httpx.AsyncClient


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """
    Initialise shared resources on startup, clean up on shutdown.
    Replaces FastAPI @app.on_event("startup") / dependency injection.
    """
    use_postgres = os.getenv("PGHOST") and os.getenv("PGDATABASE")
    if use_postgres:
        repo = PostgresRepository()
        await repo.connect()
    else:
        repo = InMemoryRepository()

    http_client = httpx.AsyncClient(timeout=10.0)

    try:
        yield AppContext(repo=repo, http_client=http_client)
    finally:
        await http_client.aclose()
        if use_postgres:
            await repo.disconnect()


# ---------------------------------------------------------------------------
# MCP Server definition
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="Opulent Horizons Lead Ingest",
    instructions=(
        "Lead ingestion and OHID resolution server for Opulent Horizons property business. "
        "Accepts leads from META, WEB, CLOUDTALK, ZOHO_SOCIAL, and ZOHO_CRM sources. "
        "Resolves or creates Opulent Horizons IDs (OHIDs) and persists to Property DB."
    ),
    lifespan=app_lifespan,
)


# ---------------------------------------------------------------------------
# Event publishing helper
# ---------------------------------------------------------------------------

async def _publish_event(ctx: AppContext, event_type: str, payload: dict) -> None:
    """Publish event to n8n/Temporal webhook (if configured)."""
    url = os.getenv("WORKFLOW_WEBHOOK_URL") or os.getenv("N8N_WEBHOOK_URL")
    if not url:
        return
    try:
        await ctx.http_client.post(url, json={"event_type": event_type, **payload})
    except httpx.HTTPError:
        pass  # Non-blocking; events are persisted to DB regardless


# ---------------------------------------------------------------------------
# Tools — Lead Ingestion
# ---------------------------------------------------------------------------

@mcp.tool()
async def ingest_lead(
    source_system: str,
    source_lead_id: str,
    channel: str,
    first_name: str,
    last_name: str,
    marketing_consent: bool,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    budget_range: Optional[str] = None,
    location: Optional[str] = None,
    property_type: Optional[str] = None,
    free_text: Optional[str] = None,
    consent_source: Optional[str] = None,
    raw_payload: Optional[dict] = None,
    ctx: Context = None,
) -> dict:
    """
    Ingest a new lead into the Opulent Horizons pipeline.

    Accepts leads from any configured source system (META, WEB, CLOUDTALK,
    ZOHO_SOCIAL, ZOHO_CRM). Resolves or creates an OHID, persists to
    Property DB, and publishes a LeadIngested workflow event.

    Returns the OHID and ingest ID for downstream processing.
    """
    app: AppContext = ctx.request_context.lifespan_context

    lead = LeadIngestRequest(
        source_system=source_system,
        source_lead_id=source_lead_id,
        channel=channel,
        person=Person(
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
        ),
        lead_details=LeadDetails(
            budget_range=budget_range,
            location=location,
            property_type=property_type,
            free_text=free_text,
        ) if any([budget_range, location, property_type, free_text]) else None,
        consent=Consent(
            marketing=marketing_consent,
            source=consent_source,
            timestamp=datetime.now(timezone.utc),
        ),
        raw_payload=raw_payload or {},
        timestamp=datetime.now(timezone.utc),
        meta={},
    )

    ohid = await resolve_ohid(app.repo, lead)
    ingest_id = str(uuid4())
    await app.repo.insert_lead_context(ohid, ingest_id, lead)

    event = {
        "event_type": "LeadIngested",
        "event_id": ingest_id,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "ohid": ohid,
        "lead_ingest": lead.model_dump(),
    }
    await app.repo.insert_workflow_event(
        event_id=ingest_id,
        ohid=ohid,
        event_type="LeadIngested",
        payload=event,
        source_system=source_system,
    )

    await _publish_event(app, "LeadIngested", event)
    await ctx.info(f"Lead ingested: OHID={ohid}, source={source_system}")

    return {
        "ohid": ohid,
        "ingest_id": ingest_id,
        "source_system": source_system,
        "status": "ingested",
    }


# ---------------------------------------------------------------------------
# Tools — CloudTalk Webhook Processing
# ---------------------------------------------------------------------------

@mcp.tool()
async def process_cloudtalk_event(
    event_type: str,
    call_id: str,
    direction: str,
    from_number: str,
    to_number: str,
    recording_url: Optional[str] = None,
    raw: Optional[dict] = None,
    ctx: Context = None,
) -> dict:
    """
    Process a CloudTalk telephony event (call started, completed, etc.).

    Persists the event as a workflow event and publishes for downstream
    processing (call transcription, AI summary, lead matching).
    """
    app: AppContext = ctx.request_context.lifespan_context
    event_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()

    if event_type in ("call.started", "call.ringing"):
        internal_event_type = "CallReceived"
    else:
        internal_event_type = "CallCompleted"

    event = {
        "event_type": internal_event_type,
        "event_id": event_id,
        "occurred_at": now,
        "call": {
            "call_id": call_id,
            "direction": direction.upper(),
            "from": from_number,
            "to": to_number,
            "recording_url": recording_url,
        },
        "ohid": None,
    }

    await app.repo.insert_workflow_event(
        event_id=event_id,
        ohid=None,
        event_type=internal_event_type,
        payload=event,
        source_system="CLOUDTALK",
    )

    await _publish_event(app, internal_event_type, event)
    await ctx.info(f"CloudTalk event processed: {internal_event_type} call_id={call_id}")

    return {"event_id": event_id, "event_type": internal_event_type, "accepted": True}


# ---------------------------------------------------------------------------
# Tools — Notion Webhook Processing
# ---------------------------------------------------------------------------

@mcp.tool()
async def process_notion_event(
    payload: dict,
    ctx: Context = None,
) -> dict:
    """
    Process a Notion webhook event. Handles verification challenges
    and persists events for workflow processing.
    """
    if "challenge" in payload:
        return {"challenge": payload["challenge"]}

    app: AppContext = ctx.request_context.lifespan_context
    event_type = payload.get("type", "notion.event")
    event_id = payload.get("id", str(uuid4()))
    now = datetime.now(timezone.utc).isoformat()

    event = {
        "event_type": "NotionEvent",
        "event_subtype": event_type,
        "event_id": event_id,
        "occurred_at": now,
        "payload": payload,
    }
    await app.repo.insert_workflow_event(
        event_id=event_id,
        ohid=None,
        event_type="NotionEvent",
        payload=event,
        source_system="NOTION",
    )

    await _publish_event(app, "NotionEvent", event)

    return {"event_id": event_id, "accepted": True}


# ---------------------------------------------------------------------------
# Tools — OHID Lookup
# ---------------------------------------------------------------------------

@mcp.tool()
async def lookup_ohid(
    email: Optional[str] = None,
    phone: Optional[str] = None,
    ctx: Context = None,
) -> dict:
    """
    Look up an existing Opulent Horizons ID (OHID) by email or phone.
    Returns the OHID if found, or indicates no match.
    """
    if not email and not phone:
        return {"error": "At least one of email or phone is required", "found": False}

    app: AppContext = ctx.request_context.lifespan_context
    ohid = await app.repo.find_ohid_by_contact(email, phone)

    if ohid:
        return {"ohid": ohid, "found": True}
    return {"found": False, "message": "No matching OHID found"}


# ---------------------------------------------------------------------------
# Tools — Signature Verification (utility)
# ---------------------------------------------------------------------------

@mcp.tool()
def verify_webhook_signature(
    body_hex: str,
    signature: str,
    source: str = "cloudtalk",
) -> dict:
    """
    Verify a webhook signature for CloudTalk or Notion payloads.
    Body should be provided as hex-encoded string.
    """
    body = bytes.fromhex(body_hex)

    if source == "cloudtalk":
        secret = os.getenv("CLOUDTALK_WEBHOOK_SECRET", "")
        mac = hmac.new(secret.encode(), msg=body, digestmod=hashlib.sha256)
        valid = hmac.compare_digest(mac.hexdigest(), signature)
    elif source == "notion":
        secret = os.getenv("NOTION_WEBHOOK_SECRET", "")
        sig = signature.split("=", 1)[1] if signature.startswith("sha256=") else signature
        digest = hmac.new(secret.encode(), msg=body, digestmod=hashlib.sha256).hexdigest()
        valid = hmac.compare_digest(digest, sig)
    else:
        return {"valid": False, "error": f"Unknown source: {source}"}

    return {"valid": valid, "source": source}


# ---------------------------------------------------------------------------
# Resources — Lead Pipeline Status
# ---------------------------------------------------------------------------

@mcp.resource("status://pipeline")
def pipeline_status() -> str:
    """Current pipeline configuration and health status."""
    return json.dumps({
        "server": "Opulent Horizons Lead Ingest",
        "version": "1.0.0",
        "sources": ["META", "WEB", "CLOUDTALK", "ZOHO_SOCIAL", "ZOHO_CRM"],
        "channels": ["WEB_FORM", "META_LEAD_AD", "INBOUND_CALL", "OUTBOUND_CALL", "SOCIAL", "CRM"],
        "database": "connected" if os.getenv("PGHOST") else "in-memory",
        "workflow_webhook": bool(
            os.getenv("WORKFLOW_WEBHOOK_URL") or os.getenv("N8N_WEBHOOK_URL")
        ),
    }, indent=2)


# ---------------------------------------------------------------------------
# Middleware — correlation ID + audit logging for all tools
# ---------------------------------------------------------------------------

wrap_tool_with_logging(mcp)

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Opulent Horizons Lead Ingest MCP Server")
    parser.add_argument(
        "--transport", choices=["stdio", "streamable-http", "sse"],
        default="stdio", help="Transport mechanism (default: stdio)"
    )
    parser.add_argument("--port", type=int, default=8001, help="HTTP port (default: 8001)")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP host (default: 0.0.0.0)")
    args = parser.parse_args()

    if args.transport != "stdio":
        # host/port are constructor-level settings — mutate before run()
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.settings.json_response = True

    mcp.run(transport=args.transport)
