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
│   │   │   ├── models.py             # 11 SQLAlchemy models
│   │   │   └── migrations/           # Alembic (async)
│   │   ├── modules/
│   │   │   ├── whatsapp/             # Meta Cloud API webhook, coexistence, provisioning, Twilio number purchase
│   │   │   ├── ai/                   # Claude/OpenAI integration (tool-use), prompts, patient + doctor tools, tool_helpers, audio transcription
│   │   │   ├── conversation/         # Session store (Redis), base_manager + managers (patient + doctor), state (working memory), grounding (reply validator), tracing
│   │   │   ├── scheduling/           # Availability engine, unified booking engine (booking.py), appointments CRUD, blocks
│   │   │   ├── urgencies/            # Urgent-appointment requests (doctor-in-the-loop overbooking): service, templates, Celery notify + timeout
│   │   │   ├── reminders/            # One periodic sweep dispatches every due reminder (week/day-before+confirm, 6h, doctor brief, check-in, follow-up)
│   │   │   ├── offices/              # Office/practice CRUD
│   │   │   ├── patients/             # Patient CRUD
│   │   │   ├── notifications/        # Configurable doctor notifications (new appointment/patient, cancellation, reschedule, pre-consultation brief, unconfirmed summary, arrival)
│   │   │   ├── audit/                # Post-action write audit (Rule 12): action vs. DB + Google Calendar
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
- **AI**: Pluggable provider via `AI_PROVIDER` (`openai` | `anthropic`). **Default is `openai`.** `anthropic_service.py`, `openai_service.py` (/v1/chat/completions) and `openai_responses_service.py` (/v1/responses) all implement the same tool-use interface. The factory routes reasoning-first models (gpt-5.6+, o-series) to the Responses service, because OpenAI rejects function tools + reasoning on chat/completions — see the header comments in both OpenAI services for the parameter matrix. The conversation flow is **tool-use based** (the LLM calls tools), not intent-detection/state-machine.
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

### Database models (app/db/models.py) — 11 models (Office, AvailabilitySchedule, TimeBlock, Patient, Appointment, UrgencyRequest, ReminderRule, Conversation, Message, GoogleCalendarEvent, AiTurnTrace)
- `Office` — the practice/consultorio (tenant). Onboarding writes structured fields here (`services`, `insurances`, `emergency_symptoms`, `intake_questions`, `assistant_gender`, `secondary_owner_phone`), seeded from the curated catalogues in `app/core/catalogs.py`; `custom_prompt` remains only as the free-text Settings field
- `AvailabilitySchedule` — weekly schedule (day_of_week, start_time, end_time, duration, buffer)
- `TimeBlock` — unavailable periods (vacations, etc.)
- `Patient` — identified by whatsapp_id
- `Appointment` — the core entity (status: scheduled → confirmed → completed)
- `UrgencyRequest` — a patient's urgent-appointment request awaiting doctor approval (status: pending → approved/rejected/expired); on approval it books a (possibly overbooked) `type="urgent"` appointment
- `ReminderRule` — per-office reminder configuration (reminder_type, offset_minutes, enabled)
- `Conversation` — WhatsApp conversation thread
- `Message` — individual messages (incoming/outgoing, with delivery_status)
- `GoogleCalendarEvent` — synced calendar events
- `AiTurnTrace` — one row per assistant turn (either channel): model/effort, every tool call with args and result, reply-validator findings, reply, outcome, tokens, latency. Diagnosis data ("why did the bot say that"); patient data, so it lives in the DB scoped by `office_id` (RLS on), pruned after 30 days by the `prune_turn_traces` beat task

> **Note:** `Waitlist` was removed (migration `f1a2b3c4d5e6_drop_waitlist_table`). Do not reference it.

### Enums (app/core/constants.py)
All enums use string values in English:
- `AppointmentStatus`: scheduled, confirmed, cancelled, completed, no_show
- `WhatsAppMode`: coexistence, dedicated, new
- `ConversationStatus`: active, waiting_confirmation, paused_by_doctor, completed, abandoned
- `ReminderType`: week_before, day_before, 6h, doctor_brief, at_time, post_appointment (timing via `ReminderRule` / `DEFAULT_REMINDER_RULES`). `day_before` is one message that reminds *and* asks to confirm (interactive buttons in-window) — it replaced the separate daily "confirmation requests" job, which sent a near-duplicate of it. `doctor_brief` (-15 min) is doctor-facing. Those two and `at_time` skip the clamp; every other patient-facing reminder is clamped into the sending window (Rule 15, `reminders/scheduler.clamp_to_sending_window`) so a 6h offset on a 9am cita goes out at 8am, never at 3am
- `ArrivalStatus`: on_the_way, arrived, no_answer (waiting room; stored on `Appointment.arrival_status`)
- `BlockOrigin`: manual, google_calendar, holiday (statutory MX holidays seeded as full-day `TimeBlock`s at office creation)

> The tool-use rewrite removed intent detection entirely — there is no `Intent` enum and no state machine.

### Doctor channel
An office has one or two doctor-channel numbers: `owner_phone` and the optional
`secondary_owner_phone` (a secretary). They have **identical** permissions — both receive every
alert and both can instruct the doctor assistant. Never read `owner_phone` directly: use
`whatsapp.doctor_notify.doctor_recipients(office)`, which is what `send_doctor_alert`, the urgency
notification and the webhook's `is_doctor` check all go through.

### WhatsApp coexistence
The doctor can use WhatsApp on their phone simultaneously with the bot. The pause is office-wide via the doctor `pause_bot`/`resume_bot` tools (Redis key `whatsapp:bot_paused:{office_id}`; default 60 min). While paused, incoming patient messages are still persisted to the conversation history (the bot just stays silent). ⚠️ Pausing automatically on a doctor's own outbound message is not implemented (it needs Meta's `message_echoes` webhook field); the doctor pauses explicitly.

### Availability engine (modules/scheduling/availability.py)
Calculates free slots by: getting weekly schedules → generating all possible slots → subtracting existing appointments → subtracting time blocks → checking Google Calendar freebusy. Results cached in Redis (5 min TTL). Slot locking via Redis SETNX (60s) prevents double-booking.

### Booking engine (modules/scheduling/booking.py)
`book_appointment()` is the **single** path that creates appointments — used by the patient tool (`confirm_booking`), the doctor tool and the dashboard service. It does: slot validation (`check_slot_bookable`) → Redis slot lock → Google Calendar event → insert → cache invalidation. It does *not* schedule reminders: the periodic sweep derives those from the row it writes.
`allow_conflict` is **not** a blanket override: validation always runs, and it only tolerates conflicts whose kind is in `OVERRIDABLE_CONFLICTS` (another appointment, or a raw Google freebusy period — our own appointments are mirrored there). A `TimeBlock` and the office's working hours stay hard (Rule 11). `check_slot_bookable` returns a typed `SlotConflict(kind, message)`. `booked_by_patient_id` records who asked for the appointment, so a parent who booked for their child keeps the right to cancel it (Rule 8). `rescheduled_from` points at the appointment this one replaces — every reschedule sets it, which is what lets a stale id resolve forward (`tool_helpers.resolve_active_appointment`) and what the doctor's "se movió una cita" notice reads. It flushes but never commits (callers own the transaction). Do not create `Appointment` rows anywhere else (exception: the urgency-approval overbook path in `urgencies/service.py`).

### Conversation managers (modules/conversation/)
`BaseToolConversationManager` (base_manager.py) holds the shared machinery: message extraction (voice notes are transcribed with Whisper via `ai/transcription.py` when `OPEN_AI_KEY` is set; interactive button taps arrive as their title text), the tool-use loop (on iteration-budget exhaustion it makes a final `tool_choice="none"` call so the model closes the turn with what it has), and text-only history.

**Two invariants keep what the assistant says in step with what it wrote.** (1) Each tool call runs in its own SAVEPOINT (`execute_tool` / `execute_doctor_tool`), so a handler that raises leaves nothing behind and the session stays usable — before this, a partial write was still committed at the end of the turn while the patient was told it had failed, and the poisoned session made every later call in the turn fail too. (2) A mutating tool (`MUTATING_TOOLS` / `DOCTOR_MUTATING_TOOLS`) never runs twice with identical arguments in one turn; the repeat gets the first result. The model may emit parallel tool calls, and two identical `create_appointment` calls used to book once and then report the first booking back as "ya tienes una cita ese día". Queued side effects go through `app/core/celery_dispatch.dispatch`, which logs a broker failure instead of raising it into the handler — a late notification is recoverable, a lie about what happened is not. **Persisted history (Redis) contains only plain user/assistant text turns** — provider-specific tool chains live in a per-turn working copy and are discarded, so switching `AI_PROVIDER` never breaks live sessions. Managers receive the raw webhook `message` dict directly (no payload re-wrapping) — or a list of them: the webhook coalesces a burst from one sender into one turn (see Redis `inbox:*`). If the LLM itself fails (`AIServiceError`), the patient/doctor gets a fixed "problema técnico" reply and the incoming message and session are still saved — never silence.

**What the tools established survives the turn: `ConversationState`** (`conversation/state.py`, stored in the session; the doctor's under `doctor_state:*`). Offered slots (with their exact `slot_id`), the patient's known appointments, a booking draft awaiting the patient's yes, and a code-written record of every executed write (`recent_actions`, filled by the tool loop for every tool in `MUTATING_TOOLS`) are rendered into the dynamic prompt as `ESTADO DE LA CONVERSACIÓN` every turn. Before this, the model rebuilt "la opción 2" and "las 4" from its own prose — the source of wrong dates, 04:00-instead-of-16:00 and "dijo que agendó y no agendó".

**Patient booking is draft → confirm.** `prepare_booking(slot_id, for_self, …)` validates the slot *now* (`check_slot_bookable`), stores a draft and returns a code-written summary; `confirm_booking()` (no arguments) writes exactly that draft via `book_appointment` (or the reschedule path when `replaces_appointment_id` is set). There is no free-form `create_appointment`/`reschedule_appointment` in the patient flow any more; attendance confirmation is `confirm_attendance`. Tools return dates/times as `label` (to show) + `slot_id` (to send back) — the model copies, never converts.

**Every reply is validated before it's sent** (`conversation/grounding.py`): a claimed action must be backed by a successful tool (`TOOL_CLAIMS` / `DOCTOR_TOOL_CLAIMS`), every clock time must appear in the evidence, and weekday/date pairs must match the calendar. One corrective pass; a false claim that survives it becomes a safe fallback. Findings go to `ai_turn_traces`.

### Urgencias (urgent appointments) — doctor-in-the-loop
Patient signals urgency → patient tool `request_urgent_appointment` creates an `UrgencyRequest` (pending) and enqueues two Celery tasks (`app/modules/urgencies/tasks.py`): `notify_doctor_urgency_task` (countdown ~5s, so the request commits first) pings the doctor on WhatsApp, and `expire_urgency_request_task` (eta = now + `URGENCY_APPROVAL_TIMEOUT_MINUTES`) is the timeout fallback. The doctor approves/rejects by replying — `DoctorConversationManager` injects pending requests into the doctor prompt (`URGENCIAS PENDIENTES`) and the doctor tool `resolve_urgent_request` books the (overbooked) `type="urgent"` appointment and notifies the patient. The bot never overbooks without the doctor's approval. If the doctor doesn't reply in time, the timeout marks the request `expired` and offers the patient the next normal slot. Doctor 24h-window detection uses a Redis key (`doctor_last_inbound:{office_id}`), not the `Message` table, because doctor messages aren't persisted there. Requires a Meta-approved template `urgency_alert` (param: patient_name) for the out-of-window doctor alert.

### Sala de espera (waiting-room check-in)
The doctor gets their pre-consultation brief at `doctor_brief` (-15 min) whether or not the patient ever answers; at the appointment's start time the `at_time` reminder rule fires `send_arrival_check`
(`reminders/tasks.py`): interactive buttons («Ya llegué» / «Voy en camino») in-window, the
`arrival_check_in` template outside it. A tapped button reaches the model as its title text — the
button id is dropped on the way in — so the task primes the patient's session
(`active_appointment_id` + status `waiting_arrival_report`), which gates the `LLEGADA PENDIENTE`
prompt block. The patient tool `report_arrival` writes `arrival_status` / `arrival_reported_at` /
`arrival_eta_minutes` and enqueues the doctor alert, which carries the pre-consultation brief
(motivo, last visit, internal note) in the same message. `scheduling/waiting_room.get_waiting_room`
reads today's reports back into the doctor prompt as `SALA DE ESPERA`, so the doctor can ask who is
outside; telling a patient to wait needs no new code — it is the existing `send_message_to_patient`
draft-and-approve flow.

### Write audit (Rule 12)
`audit/` verifies, ~20s after every appointment write, that what the action reported matches the
appointments table **and** the doctor's Google Calendar. It exists because `book_appointment`
deliberately swallows Google Calendar errors (a GCal hiccup must not cost the patient their
booking), which leaves an appointment that exists for us and not for the doctor. Divergences reach
the doctor over WhatsApp (`doctor_sync_warning` out of window) and Sentry, deduped per
appointment+kind for 24h. A Google outage is "couldn't check", not a divergence — it never alerts.

### Patient notices for dashboard changes (Rule 9)
Cancelling or rescheduling from the dashboard notifies the patient
(`scheduling/patient_notify.py`), updates Google Calendar and enqueues a write audit. These notices
are deterministic templates, not model-written text, so they skip the draft-and-approve gate — the
doctor's action in the dashboard is the approval. They retry on send failure and, once retries are
spent, escalate to the doctor: a notice that silently fails is the outcome Rule 9 forbids.

### Redis key patterns
- `session:{whatsapp_id}:{office_id}` — conversation context (TTL 24h)
- `whatsapp:bot_paused:{office_id}` — bot pause (office-wide; single source of truth, set by the doctor `pause_bot` tool, checked in the webhook router)
- `avail_cache:{office_id}:{date}` — availability cache (TTL 5min)
- `slot_lock:{office_id}:{datetime}` — anti-collision lock (TTL 60s); taken by every booking path (patient tool, doctor tool, dashboard) before inserting, and **released as soon as the appointment is cancelled or moved** — otherwise the slot reads as free everywhere and still refuses to be booked for another minute
- `wamsg_dedup:{message_id}` — webhook idempotency (TTL 24h); Meta retries are skipped
- `conv_lock:{office_id}:{sender}` — per-conversation turn serialization (TTL 120s); a second message from the same sender waits for the previous turn
- `doctor_last_inbound:{office_id}` — doctor's last inbound timestamp (TTL 24h), for the doctor service-window check
- `doctor_state:{office_id}` — the doctor conversation's `ConversationState` (TTL 24h); the patient's lives inside `session:*`
- `inbox:{office_id}:{sender}` — queued incoming messages (TTL 10min). Whoever holds `conv_lock` waits `MESSAGE_COALESCE_SECONDS` (2.5s), then answers everything queued as one turn, and keeps draining until empty
- `doctor_msg_sent:{office_id}:{patient_id}:{hash}` — an approved doctor→patient message already sent (TTL 30min); the same text to the same patient is not sent twice (a repeated "sí, mándalo" used to resend it)
- `audit_alert:{appointment_id}:{kind}` — write-audit alert dedup (TTL 24h); a persistent divergence is reported once a day, not on every write

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
5. **Celery Beat** schedule (`celery_app.py`): `dispatch_due_reminders` every 5 min (the single reminder clock), the unconfirmed-appointments digest every 15 min, `prune_turn_traces` daily, Google Calendar watch renewal daily (`renew_google_watches`, renews channels expiring within `RENEWAL_BUFFER_DAYS`). **Nothing is scheduled at booking time.** `reminders/scheduler.py` is pure arithmetic (when each rule is due) and `reminders/tasks.dispatch_due_reminders` sweeps the appointments in range, compares each office's `ReminderRule`s against the per-type sent flags, and dispatches what is due. Far-future `eta` tasks are gone, and with them the lost-on-worker-restart, delivered-twice and nightly-reconciliation problems they created.
6. **DB base.py uses lazy initialization** — `get_engine()` and `get_async_session_maker()` create connections on first use, not at import time (required for Alembic to work)
7. **Every Celery task body runs through `app/core/task_runner.run_task`**, never `asyncio.run` directly. Each task gets its own event loop, but the engine from decision 6 is a *process* global whose asyncpg connections stay bound to the loop that opened them — so the second task in a worker process used to check out a connection whose loop was already closed and die (`attached to a different loop`, then `connection was closed in the middle of operation`). `run_task` disposes the engine inside the task's own loop, so no connection outlives its loop and the next task builds a fresh one. The API process must **not** do this: there, one long-lived pool across requests is correct.

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
```

## Testing

```bash
cd hannibal-backend
pytest tests/ -v                      # unit tests (no DB, no network) — run on every change
```

- `tests/unit/` — reply validator, strict tool schemas, `ConversationState`, date labels/capabilities, the tool loop (scripted fake model), burst coalescing (fake Redis).
- `tests/integration/` — the real patient flow (manager → tools → `book_appointment` → Postgres/Redis → traces) with a scripted model. **Destructive** (wipes/reseeds the DB): only runs with `RUN_INTEGRATION=1` and a `localhost` `DATABASE_URL` — see the module docstring for the throwaway Docker Postgres.
- `tests/evals/` — conversation scenarios with a real LLM against a running simulator: an LLM plays the patient, checks read the resulting appointments table and traces. `SIM_URL=… SIM_PASSWORD=… OPEN_AI_KEY=… python -m tests.evals.run --models openai:gpt-5.6-luna:low --repeat 3` prints pass rates per model and writes a JSON report to `tests/evals/reports/`. **Run it before and after any prompt/tool change** — it is what stops a fix in one flow from silently breaking another. Model choice is made from these numbers.
  - SIM_URL / SIM_PASSWORD / OPEN_AI_KEY are read from `hannibal-backend/.env` (real env vars win); the app's Settings ignore those extra keys.
  - **Google Calendar**: when the simulator has a calendar connected (point it at a disposable test calendar), every scenario also checks the calendar against the appointments table (each active cita has its event at its time and blocking the slot; cancelled/moved ones are transparent), and the `gcal`-tagged scenarios put "personal" events in Google to check they block slots. Without a calendar those scenarios are skipped. A simulator reset deletes from Google every event the scenario created (`app/modules/sim/gcal.py`); `POST /api/sim/gcal/purge` is a one-off cleanup of older leftovers — it only deletes events whose description carries an app marker.
