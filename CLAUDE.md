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
│   │   │   ├── whatsapp/             # Meta Cloud API webhook, coexistence, provisioning, Twilio number purchase
│   │   │   ├── ai/                   # Claude/OpenAI integration (tool-use), prompts, patient + doctor tools
│   │   │   ├── conversation/         # Session store (Redis), conversation manager (patient + doctor)
│   │   │   ├── scheduling/           # Availability engine, appointments CRUD, blocks
│   │   │   ├── reminders/            # Celery tasks (day_before, 4h, 1h, post-appointment), confirmation requests, reconciliation
│   │   │   ├── offices/              # Office/practice CRUD
│   │   │   ├── patients/             # Patient CRUD
│   │   │   ├── notifications/        # Doctor notifications (⚠️ stub — not implemented, see Known gaps)
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
- **AI**: Pluggable provider via `AI_PROVIDER` (`openai` | `anthropic`). **Default is `openai`.** Both `anthropic_service.py` and `openai_service.py` implement the same tool-use interface. The conversation flow is **tool-use based** (the LLM calls tools), not intent-detection/state-machine.
- **WhatsApp**: Meta Cloud API direct. A Twilio number-purchase path (`provisioning.buy_twilio_number`) also exists for dedicated numbers.
- **Task Queue**: Celery + Redis for reminders, reconciliation, Google Calendar watch renewal
- **Frontend**: Next.js 14 (App Router), TypeScript, Tailwind CSS, FullCalendar
- **Auth**: Supabase Auth + JWT
- **Hosting**: Railway (backend), Vercel (frontend)

## Key concepts

### Multi-tenancy
Every table has `office_id`. All queries must filter by office. Supabase RLS enforces isolation at DB level. Never query without `office_id`.

### Database models (app/db/models.py) — 9 models
- `Office` — the practice/consultorio (tenant)
- `AvailabilitySchedule` — weekly schedule (day_of_week, start_time, end_time, duration, buffer)
- `TimeBlock` — unavailable periods (vacations, etc.)
- `Patient` — identified by whatsapp_id
- `Appointment` — the core entity (status: scheduled → confirmed → completed)
- `ReminderRule` — per-office reminder configuration (reminder_type, offset_minutes, enabled)
- `Conversation` — WhatsApp conversation thread
- `Message` — individual messages (incoming/outgoing, with delivery_status)
- `GoogleCalendarEvent` — synced calendar events

> **Note:** `Waitlist` was removed (migration `f1a2b3c4d5e6_drop_waitlist_table`). Do not reference it.

### Enums (app/core/constants.py)
All enums use string values in English:
- `AppointmentStatus`: scheduled, confirmed, cancelled, completed, no_show
- `WhatsAppMode`: coexistence, dedicated, new
- `ConversationStatus`: active, waiting_confirmation, paused_by_doctor, completed, abandoned
- `ReminderType`: day_before, 4h, 1h, post_appointment (timing via `ReminderRule` / `DEFAULT_REMINDER_RULES`)

> **Vestigial enums** (defined but unused — safe to ignore/remove): `Intent`, `SubscriptionPlan`, `AppointmentType`. `Intent` predates the tool-use rewrite; the manager no longer does intent detection.

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
- **AI prompts & tools**: follow `app/modules/ai/CONVENTIONS.md`. The prompt says WHAT, the tools encode the HOW; patient and doctor flows follow the same standard. Do **not** patch prompts — change tool descriptions/handlers/code instead of stacking ad-hoc rules
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
5. **Celery Beat** schedule (`celery_app.py`): reminder reconciliation (daily 7am), confirmation requests (daily, `CONFIRMATION_REQUEST_HOUR`), Google Calendar watch renewal (every 24h). ⚠️ The watch-renewal entry points at `app.modules.google_calendar.tasks.renew_google_watches`, which **does not exist** — see Known gaps. Per-appointment reminders are enqueued with `eta` by `reminders/scheduler.py` (real `shared_task`).
6. **DB base.py uses lazy initialization** — `get_engine()` and `get_async_session_maker()` create connections on first use, not at import time (required for Alembic to work)

## Environment variables (minimum required)

```
DATABASE_URL=postgresql://...   # auto-converted to asyncpg
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...
REDIS_URL=redis://localhost:6379
AI_PROVIDER=openai              # "openai" (default) or "anthropic"
OPEN_AI_KEY=sk-...             # required when AI_PROVIDER=openai
ANTHROPIC_API_KEY=sk-ant-...   # required when AI_PROVIDER=anthropic
META_VERIFY_TOKEN=your-custom-string
META_APP_SECRET=from-meta-developers
META_APP_ID=from-meta-developers
ENCRYPTION_KEY=64-char-hex-string
JWT_SECRET=from-supabase-settings
FRONTEND_URL=https://...        # used for CORS allow-origin (single origin)
# Optional
SENTRY_DSN=...
TWILIO_ACCOUNT_SID=...          # only if using Twilio number purchase
TWILIO_AUTH_TOKEN=...
GOOGLE_CLIENT_ID=...            # Google Calendar OAuth
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=...
CONFIRMATION_REQUEST_HOUR=8     # hour (MX TZ) to send daily confirmation requests
```

## Testing

```bash
cd hannibal-backend
pytest tests/ -v
pytest tests/unit/test_availability.py -v  # availability engine has 100% coverage target
```
