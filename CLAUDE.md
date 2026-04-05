# CLAUDE.md — Project Hannibal

## What is this project?

Hannibal is a multi-tenant SaaS that provides an intelligent WhatsApp assistant for independent professionals (doctors, psychologists, etc.) in Mexico. Phase 1 replaces a secretary: it schedules appointments, sends reminders, handles cancellations, and follows up — all autonomously via WhatsApp.

## Repository structure

```
hannibal/
├── hannibal-backend/     # Python 3.11+ / FastAPI API server
│   ├── app/
│   │   ├── main.py                    # FastAPI app entry point + lifespan
│   │   ├── config.py                  # Pydantic BaseSettings (.env)
│   │   ├── core/                      # Cross-cutting: security, deps, exceptions, constants
│   │   ├── db/
│   │   │   ├── base.py                # SQLAlchemy async engine (lazy init) + Base
│   │   │   ├── models.py             # 9 SQLAlchemy models
│   │   │   └── migrations/           # Alembic (async)
│   │   ├── modules/
│   │   │   ├── whatsapp/             # Meta Cloud API webhook, coexistence, provisioning
│   │   │   ├── ai/                   # Claude API integration, intent detection, prompts
│   │   │   ├── conversation/         # Session store (Redis), conversation manager
│   │   │   ├── scheduling/           # Availability engine, appointments CRUD, blocks
│   │   │   ├── reminders/            # Celery tasks (48h, 24h, 2h), reconciliation
│   │   │   ├── offices/              # Office/practice CRUD
│   │   │   ├── patients/             # Patient CRUD
│   │   │   ├── notifications/        # Doctor notifications
│   │   │   └── google_calendar/      # OAuth2, sync, watch channels
│   │   ├── middleware/               # JWT auth, rate limiting
│   │   └── utils/                    # Dates (Mexico_City TZ), phone normalization, logging
│   ├── celery_app.py                 # Celery config + beat schedule
│   ├── alembic.ini
│   ├── requirements.txt
│   └── Dockerfile
│
└── hannibal-dashboard/   # Next.js 14 / TypeScript / Tailwind CSS
    └── src/
        ├── app/
        │   ├── (auth)/               # Login, Register pages
        │   └── (dashboard)/          # Today, Schedule, Patients, Settings
        ├── components/
        │   ├── scheduling/           # ScheduleCalendar, AppointmentCard
        │   ├── coexistence/          # BotStatusBadge
        │   └── ui/                   # Button, Input, Badge, Modal, Card
        └── lib/                      # Supabase client, API client
```

## Tech stack

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy 2.0 (async), Alembic, Pydantic v2
- **Database**: Supabase (PostgreSQL) with Row Level Security
- **Cache/Broker**: Redis (sessions, Celery broker, availability cache, slot locking)
- **AI**: Claude API (Anthropic) — intent detection + conversational response generation
- **WhatsApp**: Meta Cloud API direct (no intermediaries like 360dialog)
- **Task Queue**: Celery + Redis for reminders, reconciliation, Google Calendar watch renewal
- **Frontend**: Next.js 14 (App Router), TypeScript, Tailwind CSS, FullCalendar
- **Auth**: Supabase Auth + JWT
- **Hosting**: Railway (backend), Vercel (frontend)

## Key concepts

### Multi-tenancy
Every table has `office_id`. All queries must filter by office. Supabase RLS enforces isolation at DB level. Never query without `office_id`.

### Database models (app/db/models.py)
- `Office` — the practice/consultorio (tenant)
- `AvailabilitySchedule` — weekly schedule (day_of_week, start_time, end_time, duration, buffer)
- `TimeBlock` — unavailable periods (vacations, etc.)
- `Patient` — identified by whatsapp_id
- `Appointment` — the core entity (status: scheduled → confirmed → completed)
- `Conversation` — WhatsApp conversation thread
- `Message` — individual messages (incoming/outgoing)
- `Waitlist` — patients waiting for openings
- `GoogleCalendarEvent` — synced calendar events

### Enums (app/core/constants.py)
All enums use string values in English:
- `AppointmentStatus`: scheduled, confirmed, cancelled, completed, no_show
- `Intent`: SCHEDULE, CANCEL, RESCHEDULE, CONFIRM, QUESTION, URGENT, GREETING, OTHER
- `WhatsAppMode`: coexistence, dedicated, new
- `ConversationStatus`: active, waiting_confirmation, paused_by_doctor, completed, abandoned

### WhatsApp coexistence
The doctor can use WhatsApp on their phone simultaneously with the bot. When the doctor sends a message (echo), the bot pauses for 60 minutes for that conversation. Redis key: `bot_pause:{office_id}:{conversation_id}`.

### Availability engine (modules/scheduling/availability.py)
Calculates free slots by: getting weekly schedules → generating all possible slots → subtracting existing appointments → subtracting time blocks → checking Google Calendar freebusy. Results cached in Redis (5 min TTL). Slot locking via Redis SETNX (60s) prevents double-booking.

### Redis key patterns
- `session:{whatsapp_id}:{office_id}` — conversation context (TTL 24h)
- `bot_pause:{office_id}:{conversation_id}` — coexistence pause
- `avail_cache:{office_id}:{date}` — availability cache (TTL 5min)
- `slot_lock:{office_id}:{datetime}` — anti-collision lock (TTL 60s)

## Common commands

```bash
# Backend
cd hannibal-backend
pip install -r requirements.txt
cp .env.example .env          # fill in credentials
alembic revision --autogenerate -m "description"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
celery -A celery_app worker --loglevel=info
celery -A celery_app beat --loglevel=info

# Frontend
cd hannibal-dashboard
npm install
cp .env.local.example .env.local
npm run dev
```

## Code conventions

- All code is in **English** (variable names, comments, function names)
- The AI prompts sent to Claude (in `app/modules/ai/prompts/`) contain **Spanish** text — this is intentional, the product serves Spanish-speaking users
- Reminder message templates (`app/modules/reminders/templates.py`) are also in **Spanish**
- Use `async/await` everywhere — no sync DB calls
- Logging via `structlog` (JSON format): `from app.utils.logger import get_logger`
- Config via `from app.config import settings`
- DB engine is **lazy-initialized** — import `Base` freely, engine only created when `get_engine()` is called
- Use `settings.async_database_url` (auto-converts `postgresql://` → `postgresql+asyncpg://`)
- Timezone: always `America/Mexico_City` — use `MX_TIMEZONE` from constants or `now_mx()` from utils

## Important architectural decisions

1. **Meta Cloud API directly** — no intermediary platforms. Webhook at `/api/whatsapp/webhook` (GET for verification, POST for messages)
2. **Webhook returns 200 immediately** — processing happens in FastAPI `BackgroundTasks`
3. **Verification endpoint** returns `PlainTextResponse` with just the challenge value (Meta requirement)
4. **Session context stored in Redis** (not DB) for speed — persisted to DB on conversation close
5. **Celery Beat** handles: Google Calendar watch renewal (every 24h), reminder reconciliation (daily 1am)
6. **DB base.py uses lazy initialization** — `get_engine()` and `get_async_session_maker()` create connections on first use, not at import time (required for Alembic to work)

## Environment variables (minimum required)

```
DATABASE_URL=postgresql://...   # auto-converted to asyncpg
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...
REDIS_URL=redis://localhost:6379
ANTHROPIC_API_KEY=sk-ant-...
META_VERIFY_TOKEN=your-custom-string
META_APP_SECRET=from-meta-developers
META_APP_ID=from-meta-developers
ENCRYPTION_KEY=64-char-hex-string
JWT_SECRET=from-supabase-settings
```

## Testing

```bash
cd hannibal-backend
pytest tests/ -v
pytest tests/unit/test_availability.py -v  # availability engine has 100% coverage target
```

## Current status

- Phase 1, Sprint 1-7 codebase generated
- Alembic migrations working with Supabase
- WhatsApp webhook verified with Meta
- Conversation manager has TODO markers for full integration
- Frontend pages created but need `npm install` + API connection
