# Opulent Horizons — API Endpoints & Service URLs

## Cal.com (Booking System)

| Purpose | Method | URL |
|---------|--------|-----|
| **List event types** | GET | `https://api.cal.com/v1/event-types?apiKey={CAL_API_KEY}` |
| **Team event types** | GET | `https://api.cal.com/v1/teams/190831/event-types?apiKey={CAL_API_KEY}` |
| **Get available slots** | GET | `https://api.cal.com/v1/slots?apiKey={CAL_API_KEY}&eventTypeId={id}&startTime={iso}&endTime={iso}&timeZone=Asia/Dubai` |
| **Create booking** | POST | `https://api.cal.com/v1/bookings?apiKey={CAL_API_KEY}` |
| **List teams** | GET | `https://api.cal.com/v1/teams?apiKey={CAL_API_KEY}` |

### Cal.com Identifiers

| Resource | Value |
|----------|-------|
| Org ID | `194154` (Opulent Horizons organization) |
| Team ID | `190831` (Opulent Horizons team) |
| Org slug | `opulent-horizons` |
| Org timezone | `Asia/Dubai` (UTC+4) |
| Personal event type ID | `4662330` (30 min meeting, slug: `30min`) |
| **Team event type ID** | `4719355` (Bookings Calendar Opulent Horizons, slug: `calendar-bookings`) |
| Public booking URL | `https://opulent-horizons.cal.com/opulent-horizons/calendar-bookings` |
| Personal booking URL | `https://cal.com/opulenthorizons/30min` |

### Create Booking Request Body

```json
{
  "eventTypeId": 4719355,
  "start": "2026-02-16T12:00:00+04:00",
  "end": "2026-02-16T12:30:00+04:00",
  "responses": {
    "name": "John Doe",
    "email": "john@example.com",
    "location": { "value": "integrations:daily", "optionValue": "" }
  },
  "timeZone": "Asia/Dubai",
  "language": "en",
  "metadata": {
    "source": "elevenlabs_agent",
    "conversation_id": "<conversation_id>"
  }
}
```

---

## ElevenLabs (Voice Agent)

| Purpose | URL |
|---------|-----|
| Agent ID | `agent_1901kh0bv63xe40bv1a2sa6gpphr` |
| Agent name | Nathaniel Opulent Horizons Qualification Agent v2 |
| Voice ID | `VVs5SOS5plStiKs0xCKR` (Nathaniel) |
| Twilio webhook (inbound) | Auto-set by ElevenLabs: `https://api.us.elevenlabs.io/twilio/...` |
| Inbound phone | `+447414132722` (UK, Twilio → ElevenLabs) |

### ElevenLabs Agent Tools → n8n Webhooks

| Tool Name | n8n Webhook URL |
|-----------|-----------------|
| `zoho_upsert_lead` | `https://chris-ml-s.app.n8n.cloud/webhook/c2f37918-70fb-410c-86b5-a9ce40ab6b32` |
| `calendar_schedule` | `https://chris-ml-s.app.n8n.cloud/webhook/calendar-schedule` |
| `transfer_to_number` | Native ElevenLabs transfer (no webhook) |

### Post-Call Webhook

| Purpose | URL |
|---------|-----|
| Post-call result capture | `https://chris-ml-s.app.n8n.cloud/webhook/e73b8115-f0ce-4ab0-9553-affa373b0eff` |
| Auth | HMAC signature |

---

## n8n Workflows

| Workflow | ID | Webhook Path | Status |
|----------|----|-------------|--------|
| **zoho-upsert-lead** | `GEgkgnFQFgGpew3OO_sqM` | `/webhook/c2f37918-70fb-410c-86b5-a9ce40ab6b32` | Active |
| **calendar-schedule** | `19eERjqeAbqLGHU3rlKne` | `/webhook/calendar-schedule` | Active |
| **OH - Post-Call Result Capture** | `f721ZRQqF03uQFnRQ-pE_` | `/webhook/e73b8115-f0ce-4ab0-9553-affa373b0eff` | Active |
| **Calendar Agent AI Automation** | `IJxDYA2hIfgUlwMR` | Chat trigger (not webhook) | Active |
| **Koalendar Booking Integration** | `8aJc5uQXDAFKwrkTPA6E_` | Webhook (legacy) | Active |

n8n instance base URL: `https://chris-ml-s.app.n8n.cloud`

---

## Zoho CRM

| Purpose | URL |
|---------|-----|
| API base | `https://www.zohoapis.com.au/crm/v2` |
| Token URL | `https://accounts.zoho.com.au/oauth/v2/token` |
| Data centre | Australia (`.com.au`) |
| Client ID | `1000.L0PEIEESY36SJTNWQ2HWDQP8R0BY2U` |

---

## Twilio (Telephony)

| Resource | Value |
|----------|-------|
| Account | Opulent Horizons |
| UK number (ElevenLabs) | `+447414132722` (webhook → ElevenLabs) |
| UK number (legacy) | `+447476957253` |
| US number | `+12314085906` |
| SIP Trunk (outbound) | `cal-ai-uk.pstn.twilio.com` |

---

## MCP Gateway (Local Dev)

| Server | Port | Purpose |
|--------|------|---------|
| Lead Ingest | `8001` | 5 tools: ingest, cloudtalk events, notion events, lookup, verify sig |
| Zoho CRM Sync | `8002` | 3 tools: sync, get, upsert (v1.1.0 with OAuth2 auto-refresh) |

---

## End-to-End Flow

```
Inbound Call (+447414132722)
  → Twilio webhook
  → ElevenLabs Agent (Nathaniel)
  → Agent qualifies caller (name, email, phone, intent)
  → zoho_upsert_lead tool → n8n → Zoho CRM
  → calendar_schedule tool → n8n → Cal.com API (GET slots → POST booking)
  → OR transfer_to_number → Leo (Sun-Thu 8AM-7PM GST)
  → Post-call webhook → n8n → Result capture
```
