# Hannibal Backend Modules - Creation Summary

Successfully created all specified backend modules for the Hannibal appointment scheduling system.

## Agenda Module

Core appointment scheduling and availability management.

### Files Created:

1. **`app/modules/agenda/__init__.py`**
   - Module initialization (empty)

2. **`app/modules/agenda/schemas.py`**
   - Pydantic models for all request/response DTOs
   - `SlotDisponible`: Available time slot
   - `CrearCitaRequest`, `ActualizarCitaRequest`: Appointment CRUD requests
   - `CitaResponse`: Appointment response with full data
   - `DisponibilidadRequest/Response`: Availability queries
   - `ReagendarCitaRequest`, `ConfirmarCitaRequest`, `CompletarCitaRequest`, `CancelacionCitaRequest`: Specialized requests

3. **`app/modules/agenda/disponibilidad.py`** - Core Availability Engine
   - `get_slots_disponibles()`: Generates available slots with Redis caching (5min TTL)
   - `invalidar_cache_disponibilidad()`: Clears availability cache
   - `bloquear_slot_temporal()`: Atomic slot lock to prevent race conditions
   - `liberar_slot_temporal()`: Release slot lock
   - `get_proximos_slots()`: Get availability for next N days
   - Handles: horarios_disponibilidad, existing citas, bloqueos overlaps

4. **`app/modules/agenda/citas_service.py`** - Appointment Service
   - `crear_cita()`: Create with slot validation, locking, cache invalidation
   - `cancelar_cita()`: Cancel with cache invalidation, triggers waiting list notifications
   - `reagendar_cita()`: Reschedule with lock acquisition on new slot
   - `confirmar_cita()`: Mark as confirmed
   - `completar_cita()`: Mark as attended with notes/instructions
   - `get_cita()`, `get_citas()`: Query appointments with filtering
   - TODO hooks for: Celery reminder scheduling, Google Calendar sync, waiting list notifications

5. **`app/modules/agenda/bloqueos_service.py`** - Time Blocks Service
   - `crear_bloqueo()`: Create time block (vacation, meeting, lunch)
   - `eliminar_bloqueo()`: Delete block with cache invalidation
   - `get_bloqueos()`: Query blocks by date range

6. **`app/modules/agenda/router.py`** - FastAPI Endpoints
   - `GET /api/agenda/disponibilidad` - Get available slots
   - `GET /api/agenda/proximos-slots` - Get next N days availability
   - `GET /api/agenda/citas` - List appointments (with filtering)
   - `GET /api/agenda/citas/{id}` - Get single appointment
   - `POST /api/agenda/citas` - Create appointment
   - `PUT /api/agenda/citas/{id}/confirmar` - Confirm appointment
   - `PUT /api/agenda/citas/{id}/completar` - Mark as attended
   - `PUT /api/agenda/citas/{id}/reagendar` - Reschedule
   - `DELETE /api/agenda/citas/{id}` - Cancel appointment
   - `GET /api/agenda/lista-espera` - Get waiting list
   - All endpoints JWT-protected except webhooks

## Recordatorios Module

Reminder scheduling and management system.

### Files Created:

7. **`app/modules/recordatorios/__init__.py`**
   - Module initialization (empty)

8. **`app/modules/recordatorios/templates.py`** - Spanish Message Templates
   - `recordatorio_48h()`: 48-hour appointment reminder
   - `recordatorio_24h()`: 24-hour reminder with confirmation request
   - `recordatorio_2h()`: 2-hour urgent reminder
   - `seguimiento_post()`: 2-hour post-appointment follow-up
   - `confirmacion_cita()`: Appointment confirmation message
   - `cancelacion_cita()`: Cancellation notification
   - All support: formal/informal tone, dynamic data insertion

9. **`app/modules/recordatorios/scheduler.py`** - Celery Scheduler
   - `programar_recordatorios()`: Schedule 48h, 24h, 2h reminders + confirmation check + follow-up
   - `cancelar_recordatorios()`: Cancel scheduled tasks
   - Uses Celery apply_async with eta parameter

10. **`app/modules/recordatorios/tasks.py`** - Celery Tasks
    - `enviar_recordatorio_48h()`: Send 48-hour reminder (marks flag)
    - `enviar_recordatorio_24h()`: Send 24-hour reminder
    - `enviar_recordatorio_2h()`: Send 2-hour reminder
    - `check_confirmacion()`: 1 hour before - send urgent confirmation if not confirmed
    - `seguimiento_post()`: 2 hours after - send follow-up with instructions
    - `notificar_lista_espera()`: When slot cancels - notify waiting list patients
    - All async-compatible, retrieve cita data, render templates, TODO WhatsApp send
    - Use async_session_maker for database access

11. **`app/modules/recordatorios/reconciliacion.py`** - Daily Reconciliation
    - `reconciliar_recordatorios()`: Runs daily at 1 AM
    - Finds tomorrow's appointments without all reminders sent
    - Re-programs missing reminders as safety net
    - Safety mechanism for failed scheduled tasks

## Consultorios Module

Medical office/clinic management.

### Files Created:

12. **`app/modules/consultorios/__init__.py`**
    - Module initialization (empty)

13. **`app/modules/consultorios/schemas.py`**
    - `CrearConsultorioRequest`: Create office
    - `ActualizarConsultorioRequest`: Update office
    - `ConsultorioResponse`: Office data response

14. **`app/modules/consultorios/service.py`** - CRUD Service
    - `crear_consultorio()`: Create new office
    - `obtener_consultorio()`: Get single office (with user authorization)
    - `listar_consultorios()`: List all user's offices
    - `actualizar_consultorio()`: Update office settings
    - `eliminar_consultorio()`: Delete office

15. **`app/modules/consultorios/router.py`** - FastAPI Endpoints
    - `POST /api/consultorios` - Create office
    - `GET /api/consultorios` - List offices
    - `GET /api/consultorios/{id}` - Get office
    - `PUT /api/consultorios/{id}` - Update office
    - `DELETE /api/consultorios/{id}` - Delete office
    - All JWT-protected with user authorization

## Pacientes Module

Patient/client management.

### Files Created:

16. **`app/modules/pacientes/__init__.py`**
    - Module initialization (empty)

17. **`app/modules/pacientes/schemas.py`**
    - `CrearPacienteRequest`: Create patient
    - `ActualizarPacienteRequest`: Update patient
    - `PacienteResponse`: Patient data response

18. **`app/modules/pacientes/service.py`** - CRUD Service
    - `crear_paciente()`: Create patient for consultorio
    - `obtener_paciente()`: Get patient (with consultorio authorization)
    - `listar_pacientes()`: List patients (with active filter)
    - `actualizar_paciente()`: Update patient record
    - `eliminar_paciente()`: Delete patient
    - `buscar_paciente_por_whatsapp_id()`: Find patient by WhatsApp ID

19. **`app/modules/pacientes/router.py`** - FastAPI Endpoints
    - `POST /api/pacientes` - Create patient
    - `GET /api/pacientes` - List patients
    - `GET /api/pacientes/{id}` - Get patient
    - `PUT /api/pacientes/{id}` - Update patient
    - `DELETE /api/pacientes/{id}` - Delete patient
    - `GET /api/pacientes/whatsapp/{id}` - Find by WhatsApp ID
    - All JWT-protected with consultorio authorization

## Notificaciones Module

Medical professional notifications.

### Files Created:

20. **`app/modules/notificaciones/__init__.py`**
    - Module initialization (empty)

21. **`app/modules/notificaciones/service.py`** - Notification Service
    - `notificar_medico()`: Send notification to doctor
    - Types: nueva_cita, cita_cancelada, paciente_no_confirma, nuevo_paciente, mensaje_urgente
    - Individual async handlers for each notification type
    - TODO: FCM push, WhatsApp direct, email, in-app dashboard

22. **`app/modules/notificaciones/tasks.py`** - Celery Task
    - `enviar_notificacion_medico()`: Async Celery task wrapper
    - Calls notificar_medico service

## Google Calendar Integration

Calendar synchronization and watch channels.

### Files Created:

23. **`app/modules/google_calendar/__init__.py`**
    - Module initialization (empty)

24. **`app/modules/google_calendar/auth.py`** - OAuth2 Flow
    - `get_google_oauth_url()`: Generate authorization URL with state
    - `exchange_code_for_token()`: Exchange code for access/refresh tokens
    - `refresh_google_token()`: Refresh expired tokens
    - `get_valid_google_token()`: Get current token, auto-refresh if needed
    - Stores tokens in consultorio.google_calendar_token (encrypted placeholder)

25. **`app/modules/google_calendar/service.py`** - Calendar API Operations
    - `crear_evento_calendar()`: Create Google Calendar event
    - `actualizar_evento_calendar()`: Update event
    - `eliminar_evento_calendar()`: Delete event
    - Uses valid token from auth module
    - Error handling with logging

26. **`app/modules/google_calendar/sync.py`** - Bidirectional Sync
    - `sincronizar_cita()`: Sync appointment to Google Calendar (create/update)
    - `desincronizar_cita()`: Remove appointment from Calendar
    - `sincronizar_bloqueo()`: Sync time block to Calendar
    - `desincronizar_bloqueo()`: Remove block from Calendar
    - Stores GoogleCalendarEvento records for tracking

27. **`app/modules/google_calendar/watch.py`** - Push Notifications
    - `crear_watch_channel()`: Enable push notifications (29-day expiry)
    - `eliminar_watch_channel()`: Stop watching calendar
    - `renovar_watch_channel()`: Renew expiring channel
    - Stores channel_id and expiry in consultorio

28. **`app/modules/google_calendar/router.py`** - FastAPI Endpoints
    - `GET /api/google-calendar/auth/url` - Get OAuth URL
    - `POST /api/google-calendar/auth/callback` - Process OAuth callback
    - `POST /api/google-calendar/disconnect` - Remove integration
    - `POST /api/google-calendar/watch/enable` - Enable push notifications
    - `POST /api/google-calendar/watch/disable` - Disable push notifications
    - `POST /api/google-calendar/webhook` - Webhook endpoint (NOT protected)
    - JWT-protected endpoints except webhook

## Key Architecture Patterns

### 1. Multi-Tenancy
- All operations scoped by consultorio_id
- User authorization enforced at dependency level
- get_consultorio_from_user() in each module

### 2. Caching Strategy
- Redis cache for availability (5-minute TTL)
- Automatic invalidation on cita/bloqueo changes
- Cache key: `avail_cache:{consultorio_id}:{fecha}`

### 3. Concurrency Control
- Redis SETNX for slot locking (60-second TTL)
- Prevents double-booking race conditions
- Lock acquired before DB transaction, released after

### 4. Async/Await
- All database operations async (AsyncSession)
- Async HTTP calls with httpx
- Celery tasks with asyncio bridge

### 5. Error Handling
- Custom exceptions: NotFoundError, SlotNotAvailableError, GoogleCalendarError
- Structured logging with structlog
- All errors logged with context

### 6. Integration Points
- Celery tasks for scheduling reminders
- Google Calendar API for bidirectional sync
- WhatsApp placeholder for message sending
- Firebase Cloud Messaging placeholder for doctor notifications

## TODO Implementations

The following are placeholders marked with `# TODO:` comments:

1. **WhatsApp Message Sending** - `recordatorios/tasks.py`
   - Replace placeholder with actual WhatsApp API calls

2. **Google Calendar Sync** - `agenda/citas_service.py`
   - Call sync functions on cita lifecycle events

3. **Reminder Scheduling** - `agenda/citas_service.py`
   - Call recordatorios.scheduler.programar_recordatorios()

4. **Waiting List Notifications** - `agenda/citas_service.py`
   - Trigger notificar_lista_espera task on cancellation

5. **Doctor Notifications** - `notificaciones/service.py`
   - Implement FCM, WhatsApp, email, in-app channels

6. **Google Webhook Processing** - `google_calendar/router.py`
   - Sync Google Calendar changes back to Hannibal database

7. **Token Encryption** - `google_calendar/auth.py`, `db/models.py`
   - Implement AES-256 encryption for tokens at rest

## Testing Considerations

1. Mock Celery tasks for unit tests
2. Mock httpx for Google API calls
3. Mock Redis for cache tests
4. Use SQLAlchemy in-memory SQLite for integration tests
5. Use freezegun for datetime mocking

## Future Enhancements

1. Rate limiting on API endpoints
2. Pagination for list endpoints
3. Bulk operations for appointments
4. Analytics and reporting
5. Patient self-service rescheduling portal
6. SMS reminders (Twilio integration)
7. Video call integration (Zoom/Google Meet)
8. Medical records attachment
9. Insurance verification
10. Prescription management
