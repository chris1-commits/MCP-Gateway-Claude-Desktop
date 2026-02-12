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
Lead Ingest: 5 tools [ingest_lead, process_twilio_event, process_notion_event, lookup_ohid, verify_webhook_signature]
Zoho Sync:   3 tools [sync_lead, get_zoho_lead, upsert_zoho_lead]
```

### Remaining Step: Claude Desktop Registration
The actual Claude Desktop config (`AppData\Roaming\Claude\claude_desktop_config.json`) has no `mcpServers` section yet. To activate, merge the project-level config template into the AppData config.

### Claude Code / VS Code
No conflict. Claude Code has no `.mcp.json` registered — the MCP servers are not connected to it. This is independent of Claude Desktop config.
