# Opulent Horizons MCP Gateway — Production Dockerfile
# Runs MCP servers with Streamable HTTP transport

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Copy project definition first (better layer caching)
COPY pyproject.toml .

# Copy source packages
COPY shared/ shared/
COPY servers/ servers/

# Install as editable package — resolves absolute imports (shared.models, etc.)
RUN pip install --no-cache-dir -e .

# Default: Lead Ingest server on port 8001
ENV MCP_SERVER=lead_ingest
ENV MCP_PORT=8001

EXPOSE 8001 8002

CMD ["sh", "-c", "exec python -m servers.${MCP_SERVER} --transport streamable-http --port ${MCP_PORT}"]
