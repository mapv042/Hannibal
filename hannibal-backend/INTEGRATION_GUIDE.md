# Hannibal Backend - Module Integration Guide

## Quick Start: Adding Modules to FastAPI Application

### 1. Update Main FastAPI Application (`main.py` or similar)

```python
from fastapi import FastAPI
from app.modules.agenda.router import router as agenda_router
from app.modules.pacientes.router import router as pacientes_router
from app.modules.consultorios.router import router as consultorios_router
from app.modules.google_calendar.router import router as google_calendar_router
from app.modules.notificaciones.service import notificar_medico

app = FastAPI()

# Include all routers
app.include_router(agenda_router)
app.include_router(pacientes_router)
app.include_router(consultorios_router)
app.include_router(google_calendar_router)

# Initialize logging
from app.utils.logger import configure_logging
configure_logging()
```

### 2. Configure Redis Connection

Ensure Redis is running and accessible via `settings.redis_url` (from config.py).

```bash
# .env
REDIS_URL=redis://localhost:6379/0
```

### 3. Configure Celery (for reminders)

```python
# celery_app.py
from celery import Celery
from app.config import settings

celery_app = Celery(
    "hannibal",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

# Import tasks to register them
from app.modules.recordatorios import tasks
from app.modules.notificaciones import tasks as notif_tasks
```

### 4. Create Scheduled Tasks with Celery Beat

```python
# celery_beat_schedule.py
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    "reconciliar-recordatorios": {
        "task": "app.modules.recordatorios.reconciliacion.reconciliar_recordatorios",
        "schedule": crontab(hour=1, minute=0),  # 1 AM daily
    },
}
```

## Module Dependencies

### Agenda Module
- **Dependencies**: SQLAlchemy ORM, Redis, structlog
- **External APIs**: Google Calendar (optional)
- **Celery Tasks**: recordatorios.scheduler.programar_recordatorios()
- **Database Models**: Cita, Paciente, Consultorio, HorarioDisponibilidad, Bloqueo, ListaEspera, GoogleCalendarEvento

### Recordatorios Module
- **Dependencies**: Celery, structlog, Jinja2 (for templates)
- **External APIs**: WhatsApp Business API (for sending messages)
- **Database Models**: Cita, Consultorio, Paciente
- **Configuration**: `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`

### Pacientes Module
- **Dependencies**: SQLAlchemy ORM, structlog
- **Database Models**: Paciente, Consultorio
- **No external APIs**

### Consultorios Module
- **Dependencies**: SQLAlchemy ORM, structlog
- **Database Models**: Consultorio
- **No external APIs**

### Google Calendar Module
- **Dependencies**: httpx, structlog
- **External APIs**: Google OAuth2, Google Calendar API
- **Database Models**: Consultorio, Cita, Bloqueo, GoogleCalendarEvento
- **Configuration**: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`

### Notificaciones Module
- **Dependencies**: Celery, structlog
- **External APIs**: Firebase Cloud Messaging (FCM), WhatsApp Business API, Email service
- **Database Models**: Consultorio
- **Calling from**: agenda/citas_service.py (TODO)

## Key Integration Points

### 1. Creating an Appointment (Full Flow)

```python
# In agenda/citas_service.py - create_cita()
async def crear_cita(...):
    # 1. Acquire slot lock
    lock_acquired = await bloquear_slot_temporal(...)

    # 2. Create cita record
    cita = Cita(...)
    db.add(cita)
    await db.flush()

    # 3. Invalidate availability cache
    await invalidar_cache_disponibilidad(...)

    # 4. TODO: Program reminders
    # from app.modules.recordatorios.scheduler import programar_recordatorios
    # programar_recordatorios(cita.id, cita.fecha_hora)

    # 5. TODO: Sync to Google Calendar
    # from app.modules.google_calendar.sync import sincronizar_cita
    # await sincronizar_cita(cita.id, consultorio_id, db)

    # 6. TODO: Notify doctor
    # from app.modules.notificaciones.service import notificar_medico
    # from app.modules.notificaciones.tasks import enviar_notificacion_medico
    # enviar_notificacion_medico.apply_async(
    #     args=[str(consultorio_id), "nueva_cita", {...}]
    # )

    # 7. Release lock
    await liberar_slot_temporal(...)

    await db.commit()
    return cita
```

### 2. Cancelling an Appointment

```python
# In agenda/citas_service.py - cancelar_cita()
async def cancelar_cita(...):
    cita = await db.get(Cita, cita_id)
    cita.estado = "cancelada"

    # Invalidate cache
    await invalidar_cache_disponibilidad(...)

    # TODO: Cancel reminders
    # from app.modules.recordatorios.scheduler import cancelar_recordatorios
    # cancelar_recordatorios(cita_id)

    # TODO: Remove from Google Calendar
    # from app.modules.google_calendar.sync import desincronizar_cita
    # await desincronizar_cita(cita_id, consultorio_id, db)

    # TODO: Notify waiting list
    # from app.modules.recordatorios.tasks import notificar_lista_espera
    # notificar_lista_espera.apply_async(
    #     args=[str(consultorio_id), str(cita.fecha_hora)]
    # )

    # TODO: Notify doctor
    # await notificar_medico(consultorio_id, "cita_cancelada", {...})

    await db.commit()
    return cita
```

### 3. Reminder Workflow

```
Appointment Created
    ↓
programar_recordatorios(cita_id, fecha_hora)
    ↓
Schedule 5 Celery tasks:
    • enviar_recordatorio_48h (48 hours before)
    • enviar_recordatorio_24h (24 hours before)
    • enviar_recordatorio_2h (2 hours before)
    • check_confirmacion (1 hour before)
    • seguimiento_post (2 hours after)
    ↓
Each task:
    1. Retrieve cita from database
    2. Render message using templates
    3. Send via WhatsApp API
    4. Mark flag (recordatorio_Xh_enviado = True)
    ↓
Daily 1 AM: reconciliar_recordatorios()
    - Finds tomorrow's appointments
    - Re-schedules any missing reminders
```

### 4. Google Calendar Sync Workflow

```
New Appointment Created
    ↓
sincronizar_cita(cita_id, consultorio_id, db)
    ↓
get_valid_google_token() - auto-refresh if needed
    ↓
Create event in Google Calendar
    ↓
Store GoogleCalendarEvento record
    ↓
Appointment Modified
    ↓
actualizar_evento_calendar()
    ↓
Appointment Deleted/Cancelled
    ↓
desincronizar_cita()
    ↓
eliminar_evento_calendar()
```

## Environment Variables Required

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost/hannibal_db

# Supabase (for auth)
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_KEY=xxx

# Redis
REDIS_URL=redis://localhost:6379/0

# Anthropic
ANTHROPIC_API_KEY=sk-ant-xxx

# Meta/WhatsApp
META_VERIFY_TOKEN=xxx
META_APP_SECRET=xxx
META_APP_ID=xxx

# Twilio
TWILIO_ACCOUNT_SID=xxx
TWILIO_AUTH_TOKEN=xxx

# Google OAuth
GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxx
GOOGLE_REDIRECT_URI=https://api.hannibal.app/api/google-calendar/auth/callback

# Security
ENCRYPTION_KEY=<64-char hex string for AES-256>
JWT_SECRET=<strong-secret-key>

# Celery
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# Frontend
FRONTEND_URL=https://hannibal.app

# Optional
SENTRY_DSN=https://xxx@xxx.ingest.sentry.io/xxx
```

## API Endpoints Overview

### Availability & Scheduling
- `GET /api/agenda/disponibilidad?fecha=2026-03-25&duracion_min=30`
- `GET /api/agenda/proximos-slots?dias=7`
- `POST /api/agenda/citas` (create)
- `PUT /api/agenda/citas/{id}/confirmar`
- `PUT /api/agenda/citas/{id}/completar`
- `PUT /api/agenda/citas/{id}/reagendar`
- `DELETE /api/agenda/citas/{id}`

### Patients
- `POST /api/pacientes` (create)
- `GET /api/pacientes`
- `GET /api/pacientes/{id}`
- `PUT /api/pacientes/{id}`
- `DELETE /api/pacientes/{id}`
- `GET /api/pacientes/whatsapp/{whatsapp_id}`

### Offices
- `POST /api/consultorios` (create)
- `GET /api/consultorios`
- `GET /api/consultorios/{id}`
- `PUT /api/consultorios/{id}`
- `DELETE /api/consultorios/{id}`

### Google Calendar
- `GET /api/google-calendar/auth/url` (get OAuth URL)
- `POST /api/google-calendar/auth/callback` (handle OAuth)
- `POST /api/google-calendar/disconnect`
- `POST /api/google-calendar/watch/enable`
- `POST /api/google-calendar/watch/disable`
- `POST /api/google-calendar/webhook` (unprotected)

## Testing Integration

### Unit Tests
```python
# tests/agenda/test_disponibilidad.py
import pytest
from app.modules.agenda.disponibilidad import get_slots_disponibles

@pytest.mark.asyncio
async def test_get_slots_disponibles(db_session, redis_client):
    slots = await get_slots_disponibles(
        consultorio_id=UUID("..."),
        fecha=date(2026, 3, 25),
        duracion_min=30,
        db=db_session,
        redis_client=redis_client,
    )
    assert len(slots) > 0
```

### Integration Tests
```python
# tests/agenda/test_citas_integration.py
@pytest.mark.asyncio
async def test_create_appointment_full_flow(db_session, redis_client):
    # Create consultorio
    # Create paciente
    # Create appointment
    # Verify cache invalidated
    # Verify lock released
    # Verify appointment in database
    pass
```

## Performance Considerations

1. **Availability Cache**: 5-minute TTL on Redis - adjust based on booking frequency
2. **Slot Locking**: 60-second TTL - adjust if transactions take longer
3. **Database Indexes**: Add indexes on:
   - `citas(consultorio_id, fecha_hora, estado)`
   - `horarios_disponibilidad(consultorio_id, dia_semana)`
   - `bloqueos(consultorio_id, fecha_inicio, fecha_fin)`
   - `pacientes(consultorio_id, whatsapp_id)`

4. **Pagination**: Implement pagination on list endpoints for large datasets

## Troubleshooting

### Redis Connection Issues
```python
# Verify Redis is accessible
import redis.asyncio as aioredis
redis = aioredis.from_url("redis://localhost:6379")
await redis.ping()  # Should return True
```

### Google Calendar Auth Failures
- Verify OAuth credentials in `.env`
- Check redirect URI matches exactly
- Ensure token encryption/decryption working
- Verify API is enabled in Google Cloud Console

### Celery Task Not Running
- Verify Celery worker is running: `celery -A celery_app worker`
- Verify Celery Beat scheduler running: `celery -A celery_app beat`
- Check Celery logs for errors
- Verify Redis broker accessible from worker

### Reminder Not Sending
- Check appointment datetime is correct and future
- Verify WhatsApp API credentials and phone connected
- Check template rendering for errors
- Monitor Celery task execution with Flower: `celery -A celery_app flower`

## Next Steps

1. Implement TODO items marked in code
2. Add comprehensive error handling and retry logic
3. Implement pagination for list endpoints
4. Add rate limiting to API endpoints
5. Set up monitoring and alerting
6. Create API documentation (Swagger/OpenAPI)
7. Implement audit logging for compliance
