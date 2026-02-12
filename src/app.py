"""
Opulent Horizons MCP Gateway — FastAPI Application
Provides health check and webhook endpoints.
"""

from fastapi import FastAPI

from elevenlabs_webhooks import router as elevenlabs_router

app = FastAPI(title="Opulent Horizons MCP Gateway")


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(elevenlabs_router)
