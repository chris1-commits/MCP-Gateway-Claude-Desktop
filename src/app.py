"""
Opulent Horizons — Standalone FastAPI Application

Provides the ElevenLabs webhook endpoints and a health check.
Used by tests and as a lightweight standalone server.

For production MCP+webhooks, use servers/lead_ingest.py which
mounts this alongside the MCP streamable-HTTP transport.
"""

from fastapi import FastAPI

from elevenlabs_webhooks import router as elevenlabs_router

app = FastAPI(title="Opulent Horizons MCP Gateway")


@app.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(elevenlabs_router)
