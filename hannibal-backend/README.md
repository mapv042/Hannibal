# Hannibal Backend

AI-powered medical appointment scheduling system with WhatsApp integration, Google Calendar synchronization, and intelligent appointment management.

## Features

- **WhatsApp Integration**: Receive and respond to appointment requests via WhatsApp Business API
- **Google Calendar Sync**: Automatically sync appointments across multiple Google Calendars
- **AI-Powered Scheduling**: Use Claude AI to intelligently schedule and manage appointments
- **Patient Management**: Complete patient database with contact information and appointment history
- **Appointment Tracking**: Real-time appointment status tracking and notifications
- **Multi-Consultorio Support**: Manage multiple medical offices/consultories
- **Reminder System**: Automated appointment reminders via WhatsApp and SMS

## Tech Stack

- **Framework**: FastAPI (Python)
- **Database**: PostgreSQL with SQLAlchemy ORM
- **Cache/Queue**: Redis
- **Task Queue**: Celery with Redis broker
- **Authentication**: JWT tokens
- **Error Tracking**: Sentry
- **Logging**: structlog with JSON output
- **Containerization**: Docker

## Prerequisites

- Python 3.12+
- PostgreSQL 12+
- Redis 6+
- Docker and Docker Compose (for containerized deployment)

## Local Development Setup

### 1. Clone the repository

```bash
git clone <repository-url>
cd hannibal-backend
```

### 2. Create virtual environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
# Edit .env with your configuration
```

### 5. Create database

```bash
# Run Alembic migrations
alembic upgrade head
```

### 6. Run the application

```bash
# Start FastAPI server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`

API documentation:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### 7. Run Celery worker (in a separate terminal)

```bash
celery -A celery_app worker --loglevel=info
```

### 8. Run Celery beat scheduler (in another terminal)

```bash
celery -A celery_app beat --loglevel=info
```

## Environment Variables

See `.env.example` for all required and optional environment variables:

### Database
- `DATABASE_URL`: PostgreSQL connection string

### Supabase
- `SUPABASE_URL`: Supabase project URL
- `SUPABASE_SERVICE_KEY`: Service role key for authentication

### Redis
- `REDIS_URL`: Redis connection URL

### AI
- `ANTHROPIC_API_KEY`: Claude API key

### WhatsApp/Meta
- `META_VERIFY_TOKEN`: Webhook verification token
- `META_APP_SECRET`: App secret for webhook signatures
- `META_APP_ID`: WhatsApp Business App ID

### Twilio
- `TWILIO_ACCOUNT_SID`: Account SID
- `TWILIO_AUTH_TOKEN`: Authentication token

### Google Calendar
- `GOOGLE_CLIENT_ID`: OAuth Client ID
- `GOOGLE_CLIENT_SECRET`: OAuth Client Secret
- `GOOGLE_REDIRECT_URI`: OAuth redirect URI

### Security
- `ENCRYPTION_KEY`: 64-char hex string for AES-256 encryption
- `JWT_SECRET`: JWT signing secret

### Celery
- `CELERY_BROKER_URL`: Redis URL for broker
- `CELERY_RESULT_BACKEND`: Redis URL for results

### Frontend
- `FRONTEND_URL`: Frontend URL for CORS

### Error Tracking (optional)
- `SENTRY_DSN`: Sentry project DSN

## API Endpoints

### Health Check
- `GET /health` - Service health check

### WhatsApp
- `POST /api/whatsapp/webhook` - WhatsApp webhook endpoint
- `GET /api/whatsapp/webhook` - Webhook verification
- `POST /api/whatsapp/send-message` - Send WhatsApp message

### Agenda (Appointments)
- `GET /api/agenda` - List appointments
- `POST /api/agenda` - Create appointment
- `GET /api/agenda/{id}` - Get appointment details
- `PUT /api/agenda/{id}` - Update appointment
- `DELETE /api/agenda/{id}` - Cancel appointment

### Consultories
- `GET /api/consultorios` - List medical offices
- `POST /api/consultorios` - Create consultorio
- `GET /api/consultorios/{id}` - Get consultorio details
- `PUT /api/consultorios/{id}` - Update consultorio

### Patients
- `GET /api/pacientes` - List patients
- `POST /api/pacientes` - Create patient
- `GET /api/pacientes/{id}` - Get patient details
- `PUT /api/pacientes/{id}` - Update patient

### Google Calendar
- `GET /api/google-calendar/auth-url` - Get OAuth authorization URL
- `POST /api/google-calendar/callback` - OAuth callback endpoint
- `GET /api/google-calendar/sync` - Trigger calendar sync
- `POST /api/google-calendar/watch` - Setup calendar watch

## Database Migrations

Create a new migration:

```bash
alembic revision --autogenerate -m "Description of changes"
```

Run migrations:

```bash
alembic upgrade head
```

Rollback migration:

```bash
alembic downgrade -1
```

## Testing

Run tests:

```bash
pytest
```

Run tests with coverage:

```bash
pytest --cov=app
```

## Project Structure

```
hannibal-backend/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI application entry point
│   ├── config.py               # Configuration and settings
│   ├── core/
│   │   ├── dependencies.py      # Dependency injection
│   │   ├── exceptions.py        # Custom exceptions
│   │   ├── security.py          # Security utilities
│   │   └── constants.py         # Application constants
│   ├── middleware/
│   │   ├── auth.py              # JWT authentication
│   │   └── rate_limiter.py      # Rate limiting
│   ├── db/
│   │   ├── base.py              # Database configuration
│   │   ├── models.py            # SQLAlchemy models
│   │   └── migrations/          # Alembic migrations
│   ├── modules/
│   │   ├── whatsapp/            # WhatsApp integration
│   │   ├── agenda/              # Appointment management
│   │   ├── consultorios/        # Medical office management
│   │   ├── pacientes/           # Patient management
│   │   └── google_calendar/     # Google Calendar sync
│   └── utils/
│       ├── logger.py            # Logging configuration
│       ├── dates.py             # Date utilities
│       └── phone.py             # Phone utilities
├── celery_app.py               # Celery configuration
├── alembic.ini                 # Alembic configuration
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Container image definition
├── .env.example               # Environment variables template
├── .gitignore                 # Git ignore rules
└── README.md                  # This file
```

## Deployment

### Using Docker

Build image:

```bash
docker build -t hannibal-backend:latest .
```

Run container:

```bash
docker run -d \
  --name hannibal-backend \
  -p 8000:8000 \
  --env-file .env \
  hannibal-backend:latest
```

### Using Docker Compose

Create `docker-compose.yml` with services for PostgreSQL, Redis, the app, Celery worker, and Celery beat.

### Cloud Deployment

Deployable to cloud platforms supporting Docker containers:
- Google Cloud Run
- AWS ECS
- Azure Container Instances
- Heroku
- Railway

Ensure environment variables are securely configured in your cloud platform.

## Contributing

1. Create a feature branch
2. Make your changes
3. Add tests for new functionality
4. Submit a pull request

## License

Proprietary - All rights reserved
