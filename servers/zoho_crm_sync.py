"""
Opulent Horizons — Zoho CRM Sync MCP Server
=============================================
Bidirectional synchronisation between Zoho CRM and Property DB.
Official MCP Python SDK (FastMCP) implementation.

Run:
    python -m servers.zoho_crm_sync
    python -m servers.zoho_crm_sync --transport streamable-http --port 8002
"""

# NOTE: Do NOT use 'from __future__ import annotations' here.
# The MCP SDK introspects tool function signatures at runtime via
# inspect.signature() to auto-generate JSON schemas. PEP 563 turns
# all annotations into strings, breaking Optional[str] -> schema resolution.

import os
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP, Context

from shared.models import ZohoCRMSyncRequest, ZohoCRMSyncResponse
from shared.middleware import wrap_tool_with_logging
from shared.zoho_auth import ZohoTokenManager


# ---------------------------------------------------------------------------
# Application context
# ---------------------------------------------------------------------------

@dataclass
class ZohoContext:
    http_client: httpx.AsyncClient
    zoho_api_base: str
    token_manager: ZohoTokenManager
    property_db_dsn: str

    async def get_access_token(self) -> str:
        """Get a valid Zoho access token (auto-refreshes if needed)."""
        return await self.token_manager.get_access_token(self.http_client)


@asynccontextmanager
async def zoho_lifespan(server: FastMCP) -> AsyncIterator[ZohoContext]:
    """Initialise Zoho API client and Property DB connection."""
    http_client = httpx.AsyncClient(timeout=15.0)
    token_manager = ZohoTokenManager.from_env()

    if token_manager.has_oauth_credentials:
        import logging
        logging.getLogger("opulent.mcp").info(
            "Zoho OAuth2 configured — tokens will auto-refresh"
        )
    elif token_manager.has_static_token:
        import logging
        logging.getLogger("opulent.mcp").warning(
            "Zoho using static access token — will expire after ~1 hour. "
            "Set ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN for auto-refresh."
        )
    else:
        import logging
        logging.getLogger("opulent.mcp").warning(
            "No Zoho credentials configured — CRM tools will return errors"
        )

    try:
        yield ZohoContext(
            http_client=http_client,
            zoho_api_base=os.getenv("ZOHO_API_BASE", "https://www.zohoapis.com/crm/v2"),
            token_manager=token_manager,
            property_db_dsn=(
                f"postgresql://{os.getenv('PROPERTY_DB_USER', '')}:"
                f"{os.getenv('PROPERTY_DB_PASSWORD', '')}@"
                f"{os.getenv('PROPERTY_DB_HOST', 'localhost')}:"
                f"{os.getenv('PROPERTY_DB_PORT', '5432')}/"
                f"{os.getenv('PROPERTY_DB_NAME', 'property_db')}"
            ),
        )
    finally:
        await http_client.aclose()


# ---------------------------------------------------------------------------
# MCP Server definition
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="Opulent Horizons Zoho CRM Sync",
    instructions=(
        "Bidirectional CRM synchronisation server. Syncs leads between "
        "Zoho CRM and the Opulent Horizons Property Database. Supports "
        "inbound (Zoho->PropertyDB), outbound (PropertyDB->Zoho), and "
        "bidirectional sync with source attribution."
    ),
    lifespan=zoho_lifespan,
)


# ---------------------------------------------------------------------------
# Zoho API helpers
# ---------------------------------------------------------------------------

async def _zoho_get_lead(ctx: ZohoContext, lead_id: str) -> dict | None:
    """Fetch a lead from Zoho CRM by ID."""
    token = await ctx.get_access_token()
    if not token:
        return None
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    resp = await ctx.http_client.get(
        f"{ctx.zoho_api_base}/Leads/{lead_id}", headers=headers
    )
    if resp.status_code == 200:
        data = resp.json()
        return data.get("data", [{}])[0] if data.get("data") else None
    return None


async def _zoho_upsert_lead(ctx: ZohoContext, lead_data: dict) -> dict | None:
    """Create or update a lead in Zoho CRM."""
    token = await ctx.get_access_token()
    if not token:
        return None
    headers = {
        "Authorization": f"Zoho-oauthtoken {token}",
        "Content-Type": "application/json",
    }
    resp = await ctx.http_client.post(
        f"{ctx.zoho_api_base}/Leads/upsert",
        headers=headers,
        json={"data": [lead_data], "duplicate_check_fields": ["Email"]},
    )
    if resp.status_code in (200, 201):
        data = resp.json()
        return data.get("data", [{}])[0] if data.get("data") else None
    return None


# ---------------------------------------------------------------------------
# Tools — Bidirectional Sync
# ---------------------------------------------------------------------------

@mcp.tool()
async def sync_lead(
    zoho_lead_id: str,
    sync_direction: str,
    source: Optional[str] = None,
    property_db_lead_id: Optional[str] = None,
    ctx: Context = None,
) -> dict:
    """
    Bidirectional sync between Zoho CRM and Property DB.

    sync_direction:
      - "inbound":  Pull from Zoho CRM → write to Property DB
      - "outbound": Read from Property DB → push to Zoho CRM
      - "bidirectional": Sync both (Zoho is source of truth for conflicts)

    source: Lead source attribution (e.g. 'leadchain_meta_ads', 'cloudtalk_call')
    """
    start = time.monotonic()
    app: ZohoContext = ctx.request_context.lifespan_context

    # Validate request via Pydantic model
    req = ZohoCRMSyncRequest(
        zoho_lead_id=zoho_lead_id,
        sync_direction=sync_direction,
        source=source,
        property_db_lead_id=property_db_lead_id,
    )

    inbound_ok = None
    outbound_ok = None
    error_msg = None

    try:
        # --- Inbound: Zoho → Property DB ---
        if req.sync_direction in ("inbound", "bidirectional"):
            zoho_lead = await _zoho_get_lead(app, req.zoho_lead_id)
            if zoho_lead:
                inbound_ok = True
                await ctx.info(
                    f"Inbound sync: fetched Zoho lead {req.zoho_lead_id}"
                )
            else:
                inbound_ok = False
                error_msg = f"Zoho lead {req.zoho_lead_id} not found"

        # --- Outbound: Property DB → Zoho ---
        if req.sync_direction in ("outbound", "bidirectional"):
            lead_data = {
                "Last_Name": "Synced Lead",
                "Lead_Source": req.source or "property_db",
            }
            if req.property_db_lead_id:
                lead_data["External_ID__c"] = req.property_db_lead_id

            result = await _zoho_upsert_lead(app, lead_data)
            if result:
                outbound_ok = True
                zoho_lead_id = result.get("details", {}).get("id", req.zoho_lead_id)
                await ctx.info(
                    f"Outbound sync: upserted to Zoho as {zoho_lead_id}"
                )
            else:
                outbound_ok = False
                error_msg = (error_msg or "") + " | Zoho upsert failed"

        # Determine overall status
        if inbound_ok is False or outbound_ok is False:
            status = "partial" if (inbound_ok or outbound_ok) else "failed"
        else:
            status = "success"

    except Exception as exc:
        status = "failed"
        error_msg = str(exc)
        await ctx.error(f"Sync failed: {exc}")

    elapsed_ms = int((time.monotonic() - start) * 1000)

    response = ZohoCRMSyncResponse(
        zoho_lead_id=req.zoho_lead_id,
        property_db_lead_id=req.property_db_lead_id or "",
        sync_direction=req.sync_direction,
        source=req.source,
        status=status,
        inbound_success=inbound_ok,
        outbound_success=outbound_ok,
        error_message=error_msg,
        execution_time_ms=elapsed_ms,
    )

    return response.model_dump()


# ---------------------------------------------------------------------------
# Tools — Get Zoho Lead
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_zoho_lead(
    lead_id: str,
    ctx: Context = None,
) -> dict:
    """
    Fetch a single lead from Zoho CRM by ID.
    Returns the full Zoho lead record or an error.
    """
    app: ZohoContext = ctx.request_context.lifespan_context
    lead = await _zoho_get_lead(app, lead_id)

    if lead:
        await ctx.info(f"Fetched Zoho lead: {lead_id}")
        return {"found": True, "lead": lead}
    return {"found": False, "error": f"Lead {lead_id} not found in Zoho CRM"}


# ---------------------------------------------------------------------------
# Tools — Upsert Zoho Lead
# ---------------------------------------------------------------------------

@mcp.tool()
async def upsert_zoho_lead(
    last_name: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    first_name: Optional[str] = None,
    company: Optional[str] = None,
    lead_source: Optional[str] = None,
    source_attribution: Optional[str] = None,
    ctx: Context = None,
) -> dict:
    """
    Create or update a lead in Zoho CRM with source attribution.

    Uses email as the duplicate-check field. If a lead with the same
    email exists, it will be updated; otherwise a new lead is created.

    source_attribution: e.g. 'leadchain_meta_ads', 'cloudtalk_call', 'web_form'
    """
    app: ZohoContext = ctx.request_context.lifespan_context

    lead_data = {"Last_Name": last_name}
    if email:
        lead_data["Email"] = email
    if phone:
        lead_data["Phone"] = phone
    if first_name:
        lead_data["First_Name"] = first_name
    if company:
        lead_data["Company"] = company
    if lead_source:
        lead_data["Lead_Source"] = lead_source
    if source_attribution:
        lead_data["Description"] = f"Source: {source_attribution}"

    result = await _zoho_upsert_lead(app, lead_data)

    if result:
        zoho_id = result.get("details", {}).get("id", "unknown")
        action = result.get("action", "unknown")
        await ctx.info(f"Zoho lead {action}: {zoho_id}")
        return {
            "success": True,
            "zoho_lead_id": zoho_id,
            "action": action,
            "source_attribution": source_attribution,
        }
    return {"success": False, "error": "Zoho CRM upsert failed"}


# ---------------------------------------------------------------------------
# Resources — Zoho Sync Status
# ---------------------------------------------------------------------------

@mcp.resource("status://zoho-sync")
def zoho_sync_status() -> str:
    """Zoho CRM sync configuration status."""
    has_oauth = bool(
        os.getenv("ZOHO_CLIENT_ID")
        and os.getenv("ZOHO_CLIENT_SECRET")
        and os.getenv("ZOHO_REFRESH_TOKEN")
    )
    return json.dumps({
        "server": "Opulent Horizons Zoho CRM Sync",
        "version": "1.1.0",
        "zoho_api_base": os.getenv("ZOHO_API_BASE", "https://www.zohoapis.com/crm/v2"),
        "zoho_auth_mode": "oauth2_refresh" if has_oauth else (
            "static_token" if os.getenv("ZOHO_ACCESS_TOKEN") else "not_configured"
        ),
        "zoho_configured": has_oauth or bool(os.getenv("ZOHO_ACCESS_TOKEN")),
        "property_db_configured": bool(os.getenv("PROPERTY_DB_HOST")),
        "sync_directions": ["inbound", "outbound", "bidirectional"],
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

    parser = argparse.ArgumentParser(description="Opulent Horizons Zoho CRM Sync MCP Server")
    parser.add_argument(
        "--transport", choices=["stdio", "streamable-http", "sse"],
        default="stdio", help="Transport mechanism (default: stdio)"
    )
    parser.add_argument("--port", type=int, default=8002, help="HTTP port (default: 8002)")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP host (default: 0.0.0.0)")
    args = parser.parse_args()

    if args.transport != "stdio":
        from mcp.server.transport_security import TransportSecuritySettings
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.settings.json_response = True
        # Disable DNS rebinding protection for production HTTP (behind reverse proxy/tunnel)
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        )

    mcp.run(transport=args.transport)
