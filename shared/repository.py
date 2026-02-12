"""
Opulent Horizons — Repository Abstraction
Postgres + in-memory implementations for lead context and workflow events.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional, Any, Dict
from uuid import uuid4

from .models import LeadIngestRequest


# ---------------------------------------------------------------------------
# Abstract Repository
# ---------------------------------------------------------------------------

class Repository(ABC):
    @abstractmethod
    async def insert_lead_context(
        self, ohid: str, ingest_id: str, lead: LeadIngestRequest
    ) -> None: ...

    @abstractmethod
    async def find_ohid_by_contact(
        self, email: Optional[str], phone: Optional[str]
    ) -> Optional[str]: ...
    @abstractmethod
    async def insert_workflow_event(
        self,
        event_id: str,
        ohid: Optional[str],
        event_type: str,
        payload: Any,
        source_system: str,
    ) -> None: ...


# ---------------------------------------------------------------------------
# OHID Resolution (shared across servers)
# ---------------------------------------------------------------------------

async def resolve_ohid(repo: Repository, lead: LeadIngestRequest) -> str:
    """Resolve or generate an Opulent Horizons ID for a lead."""
    existing = await repo.find_ohid_by_contact(lead.person.email, lead.person.phone)
    return existing if existing else str(uuid4())


# ---------------------------------------------------------------------------
# Postgres Repository
# ---------------------------------------------------------------------------

def _build_database_url() -> str:
    user = os.getenv("PGUSER", "")
    pw = os.getenv("PGPASSWORD", "")
    host = os.getenv("PGHOST", "localhost")
    port = os.getenv("PGPORT", "5432")
    db = os.getenv("PGDATABASE", "")
    sslmode = os.getenv("PGSSLMODE", "")
    url = f"postgresql://{user}:{pw}@{host}:{port}/{db}"
    if sslmode:
        url += f"?sslmode={sslmode}"
    return url

class PostgresRepository(Repository):
    """Async Postgres repository using asyncpg directly (no SQLAlchemy overhead)."""

    def __init__(self):
        self._pool = None

    async def connect(self):
        import asyncpg
        self._pool = await asyncpg.create_pool(_build_database_url(), min_size=2, max_size=10)

    async def disconnect(self):
        if self._pool:
            await self._pool.close()

    async def insert_lead_context(
        self, ohid: str, ingest_id: str, lead: LeadIngestRequest
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO lead_context
                (id, ohid, source_system, source_lead_id, channel, payload, consent, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            ingest_id,
            ohid,
            lead.source_system,
            lead.source_lead_id,
            lead.channel,
            lead.model_dump_json(by_alias=True),
            lead.consent.model_dump_json(),
            datetime.now(timezone.utc),
        )
    async def find_ohid_by_contact(
        self, email: Optional[str], phone: Optional[str]
    ) -> Optional[str]:
        row = await self._pool.fetchrow(
            """
            SELECT ohid FROM lead_context
            WHERE ($1::text IS NOT NULL AND payload->'person'->>'email' = $1)
               OR ($2::text IS NOT NULL AND payload->'person'->>'phone' = $2)
            LIMIT 1
            """,
            email,
            phone,
        )
        return row["ohid"] if row else None

    async def insert_workflow_event(
        self,
        event_id: str,
        ohid: Optional[str],
        event_type: str,
        payload: Any,
        source_system: str,
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO workflow_event
                (id, ohid, event_type, payload, occurred_at, source_system)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            event_id,
            ohid,
            event_type,
            json.dumps(payload, default=str) if not isinstance(payload, str) else payload,
            datetime.now(timezone.utc),
            source_system,
        )

# ---------------------------------------------------------------------------
# In-Memory Repository (for development/testing)
# ---------------------------------------------------------------------------

class InMemoryRepository(Repository):
    def __init__(self):
        self.leads: Dict[str, Any] = {}
        self.events: Dict[str, Any] = {}

    async def insert_lead_context(
        self, ohid: str, ingest_id: str, lead: LeadIngestRequest
    ) -> None:
        self.leads[ingest_id] = {"ohid": ohid, "lead": lead}

    async def find_ohid_by_contact(
        self, email: Optional[str], phone: Optional[str]
    ) -> Optional[str]:
        for record in self.leads.values():
            p = record["lead"].person
            if (email and p.email == email) or (phone and p.phone == phone):
                return record["ohid"]
        return None

    async def insert_workflow_event(
        self,
        event_id: str,
        ohid: Optional[str],
        event_type: str,
        payload: Any,
        source_system: str,
    ) -> None:
        self.events[event_id] = {
            "ohid": ohid,
            "event_type": event_type,
            "payload": payload,
            "source_system": source_system,
        }