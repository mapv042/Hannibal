# Hannibal Dashboard

Smart WhatsApp appointment assistant dashboard for doctors and healthcare professionals.

Built with Next.js 14, React 18, Tailwind CSS, and TypeScript.

## Features

- **Dashboard Overview** - View today's appointments and key statistics
- **Full Calendar** - Interactive appointment calendar with day/week/month views
- **Patient Management** - Searchable patient list with full profiles
- **Settings** - Customize bot tone, instructions, and availability hours
- **Bot Control** - Pause/resume WhatsApp bot
- **Supabase Integration** - Secure authentication and real-time sync
- **Responsive Design** - Works on desktop and mobile devices

## Tech Stack

- **Frontend Framework**: Next.js 14 (App Router)
- **UI Components**: React 18, TypeScript
- **Styling**: Tailwind CSS 3.3
- **Calendar**: FullCalendar 6.1
- **Auth**: Supabase Auth
- **Database**: Supabase PostgreSQL
- **Icons**: Lucide React

## Getting Started

### Prerequisites

- Node.js 18+ and npm/yarn
- Supabase account and project
- Backend API running (Hannibal backend)

### Installation

1. Clone the repository:
```bash
cd hannibal-dashboard
```

2. Install dependencies:
```bash
npm install
```

3. Set up environment variables:
```bash
cp .env.local.example .env.local
```

Fill in `.env.local` with your Supabase credentials:
```
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
NEXT_PUBLIC_API_URL=http://localhost:8000
```

4. Start the development server:
```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser.

## Project Structure

```
src/
├── app/
│   ├── (auth)/              # Authentication pages
│   │   ├── login/
│   │   └── register/
│   ├── (dashboard)/         # Main dashboard pages
│   │   ├── page.tsx        # Today's view
│   │   ├── agenda/         # Calendar view
│   │   ├── pacientes/      # Patients list & detail
│   │   ├── configuracion/  # Settings
│   │   └── layout.tsx      # Dashboard layout with sidebar
│   ├── globals.css         # Global styles & Tailwind
│   ├── layout.tsx          # Root layout
│   └── page.tsx            # Root redirect
├── components/
│   ├── ui/                 # Reusable UI components
│   │   ├── Button.tsx
│   │   ├── Input.tsx
│   │   ├── Badge.tsx
│   │   ├── Modal.tsx
│   │   └── Card.tsx
│   ├── agenda/             # Calendar-specific components
│   │   ├── CalendarioFullCalendar.tsx
│   │   └── CitaCard.tsx
│   └── coexistencia/       # Bot status components
│       └── BotStatusBadge.tsx
├── lib/
│   ├── supabase.ts        # Supabase client setup & types
│   └── api.ts             # API client with auth
└── middleware.ts          # Auth middleware
```

## Authentication

The app uses Supabase Auth for:
- User registration (doctors)
- Login/logout
- Session management
- JWT token generation for API calls

Protected routes automatically redirect unauthenticated users to login.

## API Integration

All API calls are made through `ApiClient` class in `src/lib/api.ts` which:
- Automatically attaches JWT tokens from Supabase session
- Handles error responses
- Provides typed responses

### Available API Methods

- `getCitas()` - Get appointments
- `getCita()` - Get single appointment
- `createCita()` - Create appointment
- `updateCita()` - Update appointment
- `deleteCita()` - Delete appointment
- `getPacientes()` - Get patients list
- `getPaciente()` - Get patient details
- `getConsultorio()` - Get office settings
- `updateConsultorio()` - Update settings
- `pauseBot()` / `resumeBot()` - Control bot
- `getStats()` - Get analytics

## Styling

- **Colors**: Custom teal/emerald medical theme
- **Components**: Tailwind CSS utility classes
- **Responsive**: Mobile-first design with breakpoints
- **Animations**: Smooth transitions and hover effects

## Deployment

### Vercel (Recommended)

```bash
npm install -g vercel
vercel
```

### Docker

```bash
docker build -t hannibal-dashboard .
docker run -p 3000:3000 hannibal-dashboard
```

### Environment Variables for Production

Set in your hosting platform:
- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- `NEXT_PUBLIC_API_URL`

## Development

### Run tests:
```bash
npm test
```

### Build for production:
```bash
npm run build
npm start
```

### Code formatting:
```bash
npm run lint
```

## Browser Support

- Chrome/Edge (latest)
- Firefox (latest)
- Safari (latest)
- Mobile browsers (iOS Safari, Chrome Mobile)

## Contributing

1. Create a feature branch
2. Make your changes
3. Submit a pull request

## License

Proprietary - Hannibal Project

## Support

For issues or questions, contact the development team.
