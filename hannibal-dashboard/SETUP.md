# Hannibal Dashboard - Setup Instructions

## Quick Start

### 1. Install Dependencies

```bash
npm install
```

### 2. Configure Environment Variables

Copy the example environment file:
```bash
cp .env.local.example .env.local
```

Edit `.env.local` and add your configuration:

```env
# Supabase Configuration
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key-here

# Backend API URL
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Get these values from:
- **Supabase URL & Key**: Supabase project settings > API section
- **API URL**: Your Hannibal backend server address

### 3. Start Development Server

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

## Supabase Setup

### 1. Create Tables

Run these SQL commands in your Supabase SQL editor:

```sql
-- Doctors table
CREATE TABLE doctors (
  id UUID PRIMARY KEY DEFAULT auth.uid(),
  email TEXT UNIQUE NOT NULL,
  nombre TEXT NOT NULL,
  especialidad TEXT,
  ciudad TEXT,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- Consultorios table
CREATE TABLE consultorios (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  doctor_id UUID NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
  nombre_asistente TEXT NOT NULL,
  tono TEXT DEFAULT 'formal',
  prompt_personalizado TEXT,
  horarios JSONB DEFAULT '{}'::jsonb,
  estado_bot TEXT DEFAULT 'inactivo',
  numero_whatsapp TEXT,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- Pacientes table
CREATE TABLE pacientes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  consultorio_id UUID NOT NULL REFERENCES consultorios(id) ON DELETE CASCADE,
  nombre TEXT NOT NULL,
  numero_whatsapp TEXT,
  email TEXT,
  total_consultas INTEGER DEFAULT 0,
  ultima_consulta_at TIMESTAMP,
  notas TEXT,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- Citas table
CREATE TABLE citas (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  consultorio_id UUID NOT NULL REFERENCES consultorios(id) ON DELETE CASCADE,
  paciente_id UUID NOT NULL REFERENCES pacientes(id) ON DELETE CASCADE,
  fecha_hora TIMESTAMP NOT NULL,
  duracion_minutos INTEGER DEFAULT 30,
  tipo_consulta TEXT,
  estado TEXT DEFAULT 'pendiente',
  notas TEXT,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- Create indexes
CREATE INDEX citas_consultorio_idx ON citas(consultorio_id);
CREATE INDEX citas_paciente_idx ON citas(paciente_id);
CREATE INDEX citas_fecha_idx ON citas(fecha_hora);
CREATE INDEX pacientes_consultorio_idx ON pacientes(consultorio_id);
CREATE INDEX consultorios_doctor_idx ON consultorios(doctor_id);
```

### 2. Enable Row Level Security (RLS)

For each table, enable RLS:

```sql
ALTER TABLE doctors ENABLE ROW LEVEL SECURITY;
ALTER TABLE consultorios ENABLE ROW LEVEL SECURITY;
ALTER TABLE pacientes ENABLE ROW LEVEL SECURITY;
ALTER TABLE citas ENABLE ROW LEVEL SECURITY;

-- Policies
CREATE POLICY "Users can view own data" ON doctors
  FOR SELECT USING (auth.uid() = id);

CREATE POLICY "Users can view own consultorios" ON consultorios
  FOR ALL USING (doctor_id = auth.uid());

CREATE POLICY "Users can view own pacientes" ON pacientes
  FOR ALL USING (
    consultorio_id IN (
      SELECT id FROM consultorios WHERE doctor_id = auth.uid()
    )
  );

CREATE POLICY "Users can view own citas" ON citas
  FOR ALL USING (
    consultorio_id IN (
      SELECT id FROM consultorios WHERE doctor_id = auth.uid()
    )
  );
```

### 3. Enable Realtime (Optional)

For real-time updates:
1. Go to Supabase project > Realtime
2. Enable realtime for `citas`, `pacientes`, `consultorios` tables

## Backend Integration

The dashboard expects a backend API with these endpoints:

### Authentication
- All endpoints require `Authorization: Bearer {jwt_token}` header

### Endpoints

**Citas (Appointments)**
- `GET /api/citas?consultorio_id=...` - List appointments
- `GET /api/citas/hoy?consultorio_id=...` - Today's appointments
- `GET /api/citas/{id}` - Get appointment details
- `POST /api/citas` - Create appointment
- `PUT /api/citas/{id}` - Update appointment
- `DELETE /api/citas/{id}` - Delete appointment

**Pacientes (Patients)**
- `GET /api/pacientes?consultorio_id=...` - List patients
- `GET /api/pacientes/{id}` - Get patient details
- `POST /api/pacientes` - Create patient
- `PUT /api/pacientes/{id}` - Update patient

**Consultorios (Offices)**
- `GET /api/consultorios/{id}` - Get consultorio
- `PUT /api/consultorios/{id}` - Update consultorio
- `GET /api/consultorios/{id}/disponibilidad` - Get availability
- `POST /api/consultorios/{id}/pause` - Pause bot
- `POST /api/consultorios/{id}/resume` - Resume bot
- `GET /api/consultorios/{id}/stats` - Get statistics

## Development

### Project Structure

```
src/
├── app/                    # Next.js App Router pages
│   ├── (auth)/            # Login & Register
│   └── (dashboard)/       # Main dashboard routes
├── components/            # React components
│   ├── ui/               # Reusable components
│   ├── agenda/           # Calendar components
│   └── coexistencia/     # Bot control components
├── lib/                   # Utilities & API client
│   ├── api.ts            # API client
│   └── supabase.ts       # Supabase setup
└── middleware.ts          # Auth middleware
```

### Available Scripts

```bash
npm run dev      # Start dev server on port 3000
npm run build    # Build for production
npm start        # Start production server
npm run lint     # Run ESLint
```

### Component Patterns

**Using the API Client:**
```typescript
import { useApi } from '@/lib/api'

export default function MyComponent() {
  const api = useApi()

  const { data, error } = await api.getCitas(consultoridId)
}
```

**Using Supabase Auth:**
```typescript
import { createBrowserSupabaseClient } from '@/lib/supabase'

const supabase = createBrowserSupabaseClient()
const { data: { user } } = await supabase.auth.getUser()
```

## Deployment

### Vercel (Recommended)

1. Push code to GitHub
2. Import project in Vercel
3. Add environment variables in Vercel settings
4. Deploy

### Docker

```bash
docker build -t hannibal-dashboard .
docker run -p 3000:3000 \
  -e NEXT_PUBLIC_SUPABASE_URL=... \
  -e NEXT_PUBLIC_SUPABASE_ANON_KEY=... \
  -e NEXT_PUBLIC_API_URL=... \
  hannibal-dashboard
```

### Manual Server

```bash
npm run build
npm start
```

Server runs on port 3000. Set `PORT` environment variable to change.

## Troubleshooting

### "Supabase client not initialized"
- Check `.env.local` has correct `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`

### "API requests failing"
- Verify `NEXT_PUBLIC_API_URL` is correct
- Check backend is running
- Ensure JWT token is being sent (check browser Network tab)

### "Can't login"
- Verify Supabase project is properly configured
- Check email/password is correct in database
- Review Supabase Auth logs

### Calendar not showing
- Install all dependencies: `npm install`
- FullCalendar requires licenses for some plugins
- Check console for JavaScript errors

## Support

For issues or questions:
1. Check the logs in `.next/` directory
2. Review browser console (F12)
3. Check Supabase dashboard for errors
4. Review backend API logs

## Security Notes

- Never commit `.env.local` file
- Use `NEXT_PUBLIC_` prefix only for non-sensitive data
- JWT tokens are secured with httpOnly cookies (Supabase Auth)
- All API calls require valid authentication token
- RLS policies protect database access

## Performance Tips

1. Use `next/image` for images
2. Implement pagination for large lists
3. Cache API responses with `SWR` or `React Query`
4. Use `next/dynamic` for code splitting
5. Monitor Core Web Vitals in Vercel analytics

## Next Steps

1. Test user registration and login
2. Create test appointments
3. Test calendar views
4. Test bot pause/resume
5. Test patient search
6. Deploy to production
