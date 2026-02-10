"""
Opulent Horizons — Shared Middleware for MCP Servers

Provides:
  - Correlation ID generation and propagation
  - Structured JSON request/response logging
  - Timing instrumentation

Usage in server files:
    from shared.middleware import wrap_tool_with_logging

    # After defining tools, wrap them:
    wrap_tool_with_logging(mcp)
"""

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any

# ---------------------------------------------------------------------------
# Correlation ID context
# ---------------------------------------------------------------------------

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Get the current correlation ID, or generate one if not set."""
    cid = _correlation_id.get()
    if not cid:
        cid = str(uuid.uuid4())
        _correlation_id.set(cid)
    return cid


def set_correlation_id(cid: str) -> None:
    """Set the correlation ID (e.g., from an inbound HTTP header)."""
    _correlation_id.set(cid)


# ---------------------------------------------------------------------------
# Structured JSON logger
# ---------------------------------------------------------------------------

_logger = logging.getLogger("opulent.mcp")


def _setup_logger():
    """Configure structured JSON logging to stderr."""
    if _logger.handlers:
        return

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_StructuredFormatter())
    _logger.addHandler(handler)
    _logger.setLevel(logging.INFO)


class _StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.000Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "extra_data"):
            entry.update(record.extra_data)
        cid = _correlation_id.get()
        if cid:
            entry["correlation_id"] = cid
        return json.dumps(entry)


def audit_log(event_type: str, **kwargs: Any) -> None:
    """Emit a structured audit log entry."""
    _setup_logger()
    extra = {"event_type": event_type, **kwargs}
    record = _logger.makeRecord(
        name="opulent.mcp.audit",
        level=logging.INFO,
        fn="",
        lno=0,
        msg=f"{event_type}",
        args=(),
        exc_info=None,
    )
    record.extra_data = extra
    _logger.handle(record)


# ---------------------------------------------------------------------------
# Tool wrapper — adds correlation ID + timing + audit logging
# ---------------------------------------------------------------------------

def wrap_tool_with_logging(mcp_server) -> None:
    """
    Monkey-patch all registered tools on an MCP server to add:
      - Correlation ID generation per call
      - Structured audit logging (tool.start, tool.end, tool.error)
      - Duration tracking (ms)

    Call this AFTER all @mcp.tool() decorators have run.
    """
    _setup_logger()
    tool_manager = mcp_server._tool_manager

    for tool_name, tool in tool_manager._tools.items():
        original_fn = tool.fn

        async def _wrapped(*args, _orig=original_fn, _name=tool_name, **kwargs):
            cid = get_correlation_id()
            if not cid:
                cid = str(uuid.uuid4())
                set_correlation_id(cid)

            audit_log("tool.start", tool=_name)
            start = time.monotonic()

            try:
                result = await _orig(*args, **kwargs)
                duration_ms = int((time.monotonic() - start) * 1000)
                audit_log("tool.end", tool=_name, duration_ms=duration_ms)
                return result
            except Exception as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                audit_log(
                    "tool.error",
                    tool=_name,
                    duration_ms=duration_ms,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                raise

        tool.fn = _wrapped
