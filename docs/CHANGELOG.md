# Changelog

All notable changes to the Opulent Horizons MCP Gateway are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [1.0.0] - 2026-02-10

### Migration: FastAPI/JSON-RPC → Official MCP Python SDK

**Decision rationale:** FastAPI gateway was carrying unnecessary protocol overhead.
The hand-rolled JSON-RPC 2.0 dispatcher, manual method routing, and custom transport
handling are all natively provided by Anthropic's official `mcp` Python SDK. Since the
FastAPI implementation was not deeply embedded (early-stage, not fully centralised),
migration cost was low and avoids accumulating technical debt.

### Added
- `servers/lead_ingest.py` — Lead ingestion MCP server (replaces `Lead.ingest` JSON-RPC method)
  - `ingest_lead` tool — Full lead pipeline with OHID resolution
  - `process_twilio_event` tool — Twilio telephony event processing
  - `process_notion_event` tool — Notion webhook handling with challenge verification
  - `lookup_ohid` tool — OHID lookup by email/phone
  - `verify_webhook_signature` tool — Twilio/Notion signature verification
  - `status://pipeline` resource — Pipeline configuration and health
- `servers/zoho_crm_sync.py` — Zoho CRM bidirectional sync MCP server
  - `sync_lead` tool — Inbound/outbound/bidirectional lead sync
  - `get_zoho_lead` tool — Fetch single lead from Zoho CRM
  - `upsert_zoho_lead` tool — Create/update lead with source attribution
  - `status://zoho-sync` resource — Sync configuration status
- `shared/models.py` — Pydantic v2 domain models (migrated from FastAPI version)
- `shared/repository.py` — Repository abstraction with asyncpg (replaced SQLAlchemy)
- `pyproject.toml` — Dependency management with hatchling build system
- `Dockerfile` — Production container with Streamable HTTP transport
- `claude_desktop_config.json` — Pre-configured for Windows with correct `cwd` paths
- `.env.example` — Environment variable template
- `.gitignore` — Python/IDE/secrets exclusions
- `docs/CHANGELOG.md` — This file
- `docs/DEPLOYMENT_LOG.md` — Deployment and operational records

### Removed
- FastAPI dependency (`fastapi`, `uvicorn`)
- SQLAlchemy dependency (`sqlalchemy`, async session factory)
- Hand-rolled JSON-RPC 2.0 dispatcher (~80 lines)
- Manual `JSONRPC_METHODS` dictionary routing
- Custom `/rpc` HTTP endpoint
- `@app.on_event("startup")` lifecycle management

### Changed
- **Transport:** HTTP-only → stdio + SSE + Streamable HTTP (SDK-managed)
- **Tool registration:** Manual dict → `@mcp.tool()` decorator with auto schema generation
- **DB driver:** SQLAlchemy async sessions → asyncpg connection pool (direct, less overhead)
- **Lifecycle:** FastAPI startup events → `lifespan` async context manager
- **Dependency injection:** FastAPI `Depends()` → MCP `Context` object with typed lifespan
- **Architecture:** Single monolithic app → Two focused MCP servers with shared layer
- **Project location:** OneDrive documentation folder → `C:\Users\ChrisSpratt\Projects\opulent-mcp-gateway` (isolated from docs/credentials)

### Technical Debt Resolved
- Eliminated custom JSON-RPC protocol implementation that required manual maintenance
  as MCP spec evolves
- Removed SQLAlchemy abstraction layer that was unnecessary for direct Postgres queries
- Separated production code from documentation/credential storage on OneDrive

---

## [0.2.0] - 2025-12-01 (Legacy — FastAPI)

### Note
This version (`python_mcp_gateway_fast_api_design_v2.py`) has been archived.
Location: `OneDrive > Opulent Horizons Automation > MCP API Gateway`
Status: **SUPERSEDED** by v1.0.0 MCP SDK implementation.
Do not deploy or reference for new development.
