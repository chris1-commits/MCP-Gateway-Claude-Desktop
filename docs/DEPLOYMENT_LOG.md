# Opulent MCP Gateway — Deployment Log

## 2026-02-10: Bug Audit & Fixes (Session 2)

### Environment Validated
- **Windows**: Python 3.13.7, MCP SDK 1.26.0, pydantic 2.12.5, httpx 0.28.1, asyncpg 0.31.0
- **Venv**: `C:\Users\ChrisSpratt\Projects\opulent-mcp-gateway\.venv` — active and working
- **Claude Desktop**: Config at `C:\Users\ChrisSpratt\AppData\Roaming\Claude\claude_desktop_config.json`

### Bugs Found & Fixed

| # | Severity | Issue | Fix Applied |
|---|----------|-------|-------------|
| 1 | 🔴 CRITICAL | `from __future__ import annotations` in both server files breaks MCP SDK tool schema introspection (PEP 563 turns types into strings) | Removed from both `lead_ingest.py` and `zoho_crm_sync.py`, added warning comments |
| 2 | 🟡 MEDIUM | `pyproject.toml` pinned `mcp>=1.9.0` but API validated against v1.26.0 | Updated to `mcp>=1.26.0` |

### Previously Fixed (Session 1 → Session 2 gap)
These were present in the initial write but already corrected on the Windows machine before this session:
- Wrong import path (`mcp.server.mcpserver.MCPServer` → `mcp.server.fastmcp.FastMCP`)
- Invalid `version=` constructor parameter (doesn't exist in FastMCP)
- `run()` receiving `host`/`port`/`json_response` as args (they're constructor/settings params)
- Truncated `zoho_crm_sync.py` (restored to full file with all 3 tools)

### Smoke Test Results ✅
```
Lead Ingest: 5 tools [ingest_lead, process_cloudtalk_event, process_notion_event, lookup_ohid, verify_webhook_signature]
Zoho Sync:   3 tools [sync_lead, get_zoho_lead, upsert_zoho_lead]
```

### Remaining Step: Claude Desktop Registration
The actual Claude Desktop config (`AppData\Roaming\Claude\claude_desktop_config.json`) has no `mcpServers` section yet. To activate, merge the project-level config template into the AppData config.

### Claude Code / VS Code
No conflict. Claude Code has no `.mcp.json` registered — the MCP servers are not connected to it. This is independent of Claude Desktop config.

---

## 2026-02-12: Azure Remote Endpoints & Desktop Config (Phase 2)

### What Was Done

1. **Claude Desktop config updated** (`AppData\Roaming\Claude\claude_desktop_config.json`)
   - Added remote Azure endpoints with Streamable HTTP transport + Bearer auth
   - Both `opulent-lead-ingest` and `opulent-zoho-sync` configured as primary (remote)

2. **Project-level config template updated** (`claude_desktop_config.json`)
   - Remote servers (`opulent-lead-ingest`, `opulent-zoho-sync`) — Azure Container Apps URLs with `<MCP_API_KEY>` placeholder
   - Local servers (`opulent-lead-ingest-local`, `opulent-zoho-sync-local`) — stdio transport, `disabled: true`, with `<VENV_PATH>` / `<PROJECT_PATH>` placeholders

3. **Azure endpoints verified live**
   - Lead Ingest: `https://opulent-mcp-dev-lead-ingest.agreeablemeadow-00328895.australiaeast.azurecontainerapps.io/mcp` → HTTP 200
   - Zoho Sync: `https://opulent-mcp-dev-zoho-sync.agreeablemeadow-00328895.australiaeast.azurecontainerapps.io/mcp` → HTTP 200

### Azure Container Apps Deployment

| Server | URL | Transport | Auth |
|--------|-----|-----------|------|
| Lead Ingest | `https://opulent-mcp-dev-lead-ingest.agreeablemeadow-00328895.australiaeast.azurecontainerapps.io/mcp` | Streamable HTTP | Bearer token |
| Zoho Sync | `https://opulent-mcp-dev-zoho-sync.agreeablemeadow-00328895.australiaeast.azurecontainerapps.io/mcp` | Streamable HTTP | Bearer token |

### Tools Available (8 total)

**Lead Ingest (5 tools):** `ingest_lead`, `process_cloudtalk_event`, `process_notion_event`, `lookup_ohid`, `verify_webhook_signature`

**Zoho CRM Sync (3 tools):** `sync_lead`, `get_zoho_lead`, `upsert_zoho_lead`

### Activation Steps
1. Quit Claude Desktop fully (right-click tray icon → Quit)
2. Reopen Claude Desktop
3. Verify all 8 tools are discoverable in the MCP server list
