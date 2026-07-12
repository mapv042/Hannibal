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
│   │   │   ├── models.py             # 10 SQLAlchemy models
│   │   │   └── migrations/           # Alembic (async)
│   │   ├── modules/
│   │   │   ├── whatsapp/             # Meta Cloud API webhook, coexistence, provisioning, Twilio number purchase
│   │   │   ├── ai/                   # Claude/OpenAI integration (tool-use), prompts, patient + doctor tools, tool_helpers, audio transcription
│   │   │   ├── conversation/         # Session store (Redis), base_manager + conversation managers (patient + doctor)
│   │   │   ├── scheduling/           # Availability engine, unified booking engine (booking.py), appointments CRUD, blocks
│   │   │   ├── urgencies/            # Urgent-appointment requests (doctor-in-the-loop overbooking): service, templates, Celery notify + timeout
│   │   │   ├── reminders/            # Celery tasks (day_before, 4h, 1h, post-appointment), confirmation requests (interactive buttons in-window), reconciliation
│   │   │   ├── offices/              # Office/practice CRUD
│   │   │   ├── patients/             # Patient CRUD
│   │   │   ├── notifications/        # Configurable doctor notifications (new appointment/patient, cancellations, unconfirmed summary)
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
Every table has `office_id`. All queries must filter by office. **Isolation is enforced only at the application layer** — the backend connects with the Postgres superuser role (`DATABASE_URL`), which **bypasses Supabase RLS**, so RLS is *not* a safety net for the API. Every query must filter by `office_id`, and every handler that loads a row by id must verify `row.office_id == ctx.office.id` before using it (the tool handlers already do this). Treat a missing `office_id` filter as a tenant-isolation bug, not just a correctness one.

### Secrets & auth
- `Settings.validate_secrets()` runs at startup (`main.lifespan`) and **refuses to boot in production** (`ENVIRONMENT=production`) if `JWT_SECRET` is empty, `ENCRYPTION_KEY` is the all-zero default, or `META_APP_SECRET` is empty; in development it warns. `validate_jwt` also refuses an empty `JWT_SECRET` unconditionally (an empty secret makes tokens forgeable) and verifies the Supabase `aud` claim (`JWT_AUDIENCE`, default `authenticated`).
- Secrets encrypted at rest with Fernet (`ENCRYPTION_KEY`, via `app/db/types.py`): `Office.whatsapp_token` (`EncryptedText`) and `Office.google_calendar_token` (`EncryptedJSON`, OAuth access+refresh). Both read legacy plaintext rows transparently and re-encrypt on next write.
- Google Calendar OAuth uses a single-use random `state` nonce stored in Redis (`gcal_oauth_state:{nonce}`, 10-min TTL) — the callback resolves the office from the nonce, never from a client-supplied id (CSRF defense).
- Owner-scoped endpoints resolve the office from the JWT `sub` (or verify `office.user_id == sub` when an id is in the path) and return 404 — not 403 — for a non-owned office, so ids can't be enumerated.

### Database models (app/db/models.py) — 10 models (Office, AvailabilitySchedule, TimeBlock, Patient, Appointment, UrgencyRequest, ReminderRule, Conversation, Message, GoogleCalendarEvent)
- `Office` — the practice/consultorio (tenant)
- `AvailabilitySchedule` — weekly schedule (day_of_week, start_time, end_time, duration, buffer)
- `TimeBlock` — unavailable periods (vacations, etc.)
- `Patient` — identified by whatsapp_id
- `Appointment` — the core entity (status: scheduled → confirmed → completed)
- `UrgencyRequest` — a patient's urgent-appointment request awaiting doctor approval (status: pending → approved/rejected/expired); on approval it books a (possibly overbooked) `type="urgent"` appointment
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
The doctor can use WhatsApp on their phone simultaneously with the bot. The pause is office-wide via the doctor `pause_bot`/`resume_bot` tools (Redis key `whatsapp:bot_paused:{office_id}`; default 60 min). While paused, incoming patient messages are still persisted to the conversation history (the bot just stays silent). ⚠️ Automatic echo detection (`is_doctor_echo`) is a stub — it always returns False; pausing on doctor echoes is not implemented yet (requires subscribing to Meta's `message_echoes` webhook field).

### Availability engine (modules/scheduling/availability.py)
Calculates free slots by: getting weekly schedules → generating all possible slots → subtracting existing appointments → subtracting time blocks → checking Google Calendar freebusy. Results cached in Redis (5 min TTL). Slot locking via Redis SETNX (60s) prevents double-booking.

### Booking engine (modules/scheduling/booking.py)
`book_appointment()` is the **single** path that creates appointments — used by the patient tool, the doctor tool and the dashboard service. It does: slot validation (`check_slot_bookable`, skippable via `allow_conflict` for deliberate doctor overbooking) → Redis slot lock → Google Calendar event → insert → cache invalidation → reminder scheduling. It flushes but never commits (callers own the transaction). Do not create `Appointment` rows anywhere else (exception: the urgency-approval overbook path in `urgencies/service.py`).

### Conversation managers (modules/conversation/)
`BaseToolConversationManager` (base_manager.py) holds the shared machinery: message extraction (voice notes are transcribed with Whisper via `ai/transcription.py` when `OPEN_AI_KEY` is set; interactive button taps arrive as their title text), the tool-use loop (on iteration-budget exhaustion it makes a final `tool_choice="none"` call so the model closes the turn with what it has), and text-only history. **Persisted history (Redis) contains only plain user/assistant text turns** — provider-specific tool chains live in a per-turn working copy and are discarded, so switching `AI_PROVIDER` never breaks live sessions. Managers receive the raw webhook `message` dict directly (no payload re-wrapping).

### Urgencias (urgent appointments) — doctor-in-the-loop
Patient signals urgency → patient tool `request_urgent_appointment` creates an `UrgencyRequest` (pending) and enqueues two Celery tasks (`app/modules/urgencies/tasks.py`): `notify_doctor_urgency_task` (countdown ~5s, so the request commits first) pings the doctor on WhatsApp, and `expire_urgency_request_task` (eta = now + `URGENCY_APPROVAL_TIMEOUT_MINUTES`) is the timeout fallback. The doctor approves/rejects by replying — `DoctorConversationManager` injects pending requests into the doctor prompt (`URGENCIAS PENDIENTES`) and the doctor tool `resolve_urgent_request` books the (overbooked) `type="urgent"` appointment and notifies the patient. The bot never overbooks without the doctor's approval. If the doctor doesn't reply in time, the timeout marks the request `expired` and offers the patient the next normal slot. Doctor 24h-window detection uses a Redis key (`doctor_last_inbound:{office_id}`), not the `Message` table, because doctor messages aren't persisted there. Requires a Meta-approved template `urgency_alert` (param: patient_name) for the out-of-window doctor alert.

### Redis key patterns
- `session:{whatsapp_id}:{office_id}` — conversation context (TTL 24h)
- `whatsapp:bot_paused:{office_id}` — bot pause (office-wide; single source of truth, set by the doctor `pause_bot` tool, checked in the webhook router)
- `avail_cache:{office_id}:{date}` — availability cache (TTL 5min)
- `slot_lock:{office_id}:{datetime}` — anti-collision lock (TTL 60s); taken by every booking path (patient tool, doctor tool, dashboard) before inserting
- `wamsg_dedup:{message_id}` — webhook idempotency (TTL 24h); Meta retries are skipped
- `conv_lock:{office_id}:{sender}` — per-conversation turn serialization (TTL 120s); a second message from the same sender waits for the previous turn
- `doctor_last_inbound:{office_id}` — doctor's last inbound timestamp (TTL 24h), for the doctor service-window check

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
5. **Celery Beat** schedule (`celery_app.py`): reminder reconciliation (daily 7am, safety net only), confirmation requests (daily, `CONFIRMATION_REQUEST_HOUR`), Google Calendar watch renewal (every 24h via `app.modules.google_calendar.tasks.renew_google_watches`, which renews channels expiring within `RENEWAL_BUFFER_DAYS`). Per-appointment reminders are enqueued with `eta` by `reminders/scheduler.py` — every booking path (patient/doctor tools, dashboard service, urgency approval) calls `schedule_reminders_for_appointment` at creation/reschedule time.
6. **DB base.py uses lazy initialization** — `get_engine()` and `get_async_session_maker()` create connections on first use, not at import time (required for Alembic to work)

## Environment variables (minimum required)

```
DATABASE_URL=postgresql://...   # auto-converted to asyncpg
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...
REDIS_URL=redis://localhost:6379
AI_PROVIDER=openai              # "openai" (default) or "anthropic"
OPEN_AI_KEY=sk-...             # required when AI_PROVIDER=openai
OPEN_AI_MODEL=gpt-4.1-mini      # required when AI_PROVIDER=openai
ANTHROPIC_API_KEY=sk-ant-...   # required when AI_PROVIDER=anthropic
ANTHROPIC_AI_MODEL=claude-haiku-4-5-20251001     # required when AI_PROVIDER=anthropic
META_VERIFY_TOKEN=your-custom-string
META_APP_SECRET=from-meta-developers
META_APP_ID=from-meta-developers
ENCRYPTION_KEY=64-char-hex-string
JWT_SECRET=from-supabase-settings
FRONTEND_URL=https://...        # used for CORS allow-origin (single origin)
BACKEND_URL=https://...         # backend public URL; builds the Google Calendar push webhook address
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

> ⚠️ There is **no test suite yet** — `tests/` does not exist. pytest/pytest-asyncio are already in requirements; when adding tests, start with the availability engine (`compute_day_availability`, `check_slot_bookable`), the booking engine (`booking.book_appointment`) and `BaseToolConversationManager.sanitize_history`.

```bash
cd hannibal-backend
pytest tests/ -v
```
