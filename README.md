# Opulent Horizons MCP Gateway

**Official MCP Python SDK Implementation** — Migrated from FastAPI/JSON-RPC

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                   MCP Clients                         │
│   Claude Desktop │ Claude Code │ Custom Agents        │
└─────────┬────────────┬──────────────┬────────────────┘
          │ stdio      │ stdio        │ HTTP
          ▼            ▼              ▼
┌─────────────────┐  ┌──────────────────┐
│  Lead Ingest    │  │  Zoho CRM Sync   │    ← Each is a standalone
│  MCP Server     │  │  MCP Server      │      MCP server
│  (port 8001)    │  │  (port 8002)     │
└────────┬────────┘  └────────┬─────────┘
         │                    │
         ▼                    ▼
┌─────────────────────────────────────────┐
│         Shared Layer                     │
│  models.py │ repository.py               │
└────────┬──────────────┬─────────────────┘
         │              │
         ▼              ▼
┌──────────────┐  ┌──────────────┐
│ Property DB  │  │  Zoho CRM    │
│ (PostgreSQL) │  │  (REST API)  │
└──────────────┘  └──────────────┘
```

## What Changed (FastAPI → MCP SDK)

| Aspect | Before (FastAPI) | After (MCP SDK) |
|--------|-----------------|-----------------|
| **Protocol** | Hand-rolled JSON-RPC 2.0 | SDK handles automatically |
| **Transport** | HTTP only (`/rpc` endpoint) | stdio, SSE, Streamable HTTP |
| **Tool registration** | `JSONRPC_METHODS` dict | `@mcp.tool()` decorator |
| **Schema generation** | Manual | Auto from type hints |
| **Discovery** | None | Built-in MCP capability negotiation |
| **DB lifecycle** | `@app.on_event("startup")` | `lifespan` async context manager |
| **Dependency injection** | FastAPI `Depends()` | `Context` object with typed lifespan |
| **Lines of code** | ~490 | ~380 (across 2 servers + shared) |
| **Dependencies** | FastAPI, Uvicorn, SQLAlchemy | `mcp` SDK, asyncpg |

## What Carried Over Unchanged

- **Pydantic domain models** (Person, LeadDetails, Consent, etc.)
- **Repository abstraction** (Postgres + in-memory)
- **OHID resolution logic**
- **Signature verification** (CloudTalk, Notion)
- **Event publishing** (webhook to n8n/Temporal)
- **Business logic** (lead ingestion, call processing, sync)

## Quick Start

### 1. Install
```bash
pip install -e .
```

### 2. Run (stdio — for Claude Desktop / Claude Code)
```bash
# Lead Ingest server
python -m servers.lead_ingest

# Zoho CRM Sync server
python -m servers.zoho_crm_sync
```

### 3. Run (HTTP — for production / remote agents)
```bash
python -m servers.lead_ingest --transport streamable-http --port 8001
python -m servers.zoho_crm_sync --transport streamable-http --port 8002
```

### 4. Claude Desktop Configuration
Copy `claude_desktop_config.json` into your Claude Desktop config directory:
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

### 5. Claude Code Registration
```bash
claude mcp add --transport http opulent-lead-ingest http://localhost:8001/mcp
claude mcp add --transport http opulent-zoho-sync http://localhost:8002/mcp
```

## Docker Deployment
```bash
# Lead Ingest
docker build -t opulent-lead-ingest .
docker run -p 8001:8001 --env-file .env opulent-lead-ingest

# Zoho Sync
docker run -p 8002:8002 --env-file .env -e MCP_SERVER=zoho_crm_sync -e MCP_PORT=8002 opulent-lead-ingest
```

## Adding New Connectors

To add a new MCP server (e.g., BigQuery Analytics):

```python
# servers/bigquery_analytics.py
from mcp.server.fastmcp import FastMCP, Context

mcp = FastMCP("Opulent Horizons BigQuery Analytics")

@mcp.tool()
async def query_lead_analytics(
    date_from: str,
    date_to: str,
    group_by: str = "source",
    ctx: Context = None,
) -> dict:
    """Query lead analytics from BigQuery."""
    # Your implementation here
    ...

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

That's it. No JSON-RPC boilerplate, no route registration, no transport handling.

## Project Structure
```
opulent-mcp-gateway/
├── pyproject.toml              # Dependencies (mcp SDK, asyncpg, httpx)
├── Dockerfile                  # Production container
├── docker-compose.yml          # Local dev: both servers + Postgres
├── .env.example                # Environment template
├── claude_desktop_config.json  # Claude Desktop MCP registration
├── docs/
│   ├── CHANGELOG.md            # Version history and changes
│   └── DEPLOYMENT_LOG.md       # Deployment records
├── infra/
│   └── main.bicep              # Azure Container Apps IaC
├── shared/
│   ├── __init__.py
│   ├── auth.py                 # Bearer token ASGI middleware
│   ├── middleware.py            # Correlation ID + structured logging
│   ├── models.py               # Pydantic domain models
│   ├── repository.py           # DB abstraction (Postgres + in-memory)
│   ├── schema.sql              # PostgreSQL table definitions
│   └── zoho_auth.py            # OAuth2 token manager for Zoho API
├── servers/
│   ├── __init__.py
│   ├── lead_ingest.py           # Lead ingestion MCP server
│   └── zoho_crm_sync.py        # Zoho CRM sync MCP server
└── tests/
    ├── conftest.py              # Pytest fixtures
    ├── test_lead_ingest.py      # Lead ingest unit + integration tests
    ├── test_zoho_sync.py        # Zoho sync tests
    └── e2e_zoho_live.py         # End-to-end Zoho API tests
```
