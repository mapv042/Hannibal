# Hannibal Dashboard - Complete File Index

## Project Root Files (13 files)

### Configuration Files
- **package.json** - NPM dependencies and scripts
- **tsconfig.json** - TypeScript compiler configuration with path aliases
- **tailwind.config.ts** - Tailwind CSS theme with medical colors
- **postcss.config.js** - PostCSS configuration for Tailwind
- **next.config.js** - Next.js application configuration
- **.env.local.example** - Environment variables template

### Deployment Files
- **Dockerfile** - Docker multi-stage build configuration
- **.dockerignore** - Docker ignore patterns

### Git & Metadata
- **.gitignore** - Git ignore patterns for Next.js

### Documentation
- **README.md** - Project overview and quick start
- **SETUP.md** - Detailed setup instructions with SQL migrations
- **PROJECT_SUMMARY.md** - Complete project documentation
- **FILES.md** - This file

---

## Source Code (src/ directory)

### App Router Structure (src/app/)

#### Root Layout & Pages
- **layout.tsx** - Root HTML layout with fonts and metadata
- **page.tsx** - Home page that redirects to /dashboard
- **globals.css** - Global Tailwind styles and custom CSS

#### Authentication Routes (src/app/(auth)/)
- **layout.tsx** - Auth page layout with gradient background
- **login/page.tsx** - Login form (email/password via Supabase)
- **register/page.tsx** - Registration form (doctor profile creation)

#### Dashboard Routes (src/app/(dashboard)/)
- **layout.tsx** - Main dashboard layout with sidebar navigation
- **page.tsx** - "Vista del Día" (Today's appointments view)
- **agenda/page.tsx** - Calendar view with FullCalendar
- **pacientes/page.tsx** - Patient list with search functionality
- **pacientes/[id]/page.tsx** - Individual patient profile page
- **configuracion/page.tsx** - Settings page (bot config, availability, integrations)

### Components (src/components/)

#### UI Components (src/components/ui/)
Basic, reusable UI building blocks:
- **Button.tsx** - Button with variants (primary, secondary, danger, ghost)
- **Input.tsx** - Text input with labels, errors, help text
- **Badge.tsx** - Status badge component with color variants
- **Modal.tsx** - Modal dialog with escape key support
- **Card.tsx** - Card container (Card, CardHeader, CardBody, CardFooter)

#### Feature Components

**Agenda Components** (src/components/agenda/)
- **CalendarioFullCalendar.tsx** - FullCalendar integration wrapper
- **CitaCard.tsx** - Individual appointment card component

**Bot Components** (src/components/coexistencia/)
- **BotStatusBadge.tsx** - Bot status indicator with pause/resume button

### Library Code (src/lib/)

**Data & API**
- **supabase.ts** - Supabase client setup (browser, server, admin)
  - Exports: Type definitions (Consultorio, Cita, Paciente, Doctor)
  - Exports: Client factories for different contexts
- **api.ts** - API client class with JWT auth
  - Singleton pattern for single API instance
  - Methods for all CRUD operations
  - Automatic token attachment from Supabase session

### Middleware
- **middleware.ts** - Auth middleware for route protection
  - Protects /dashboard routes
  - Allows /login and /register without auth
  - Redirects unauthenticated users to login

---

## File Count & Statistics

| Category | Files | Lines of Code |
|----------|-------|---------------|
| Configuration | 5 | ~200 |
| Source TypeScript | 22 | ~2,500 |
| Documentation | 4 | ~1,000 |
| Docker | 2 | ~40 |
| Git Config | 1 | ~50 |
| **Total** | **34** | **~3,790** |

---

## Component Hierarchy

```
Root Layout
├── Auth Layout
│   ├── Login Page
│   └── Register Page
├── Dashboard Layout
│   ├── Sidebar Navigation
│   ├── Header with User Menu
│   └── Main Content
│       ├── Today Page
│       │   └── CitaCard (x multiple)
│       ├── Agenda Page
│       │   ├── CalendarioFullCalendar
│       │   └── Modal (appointment details)
│       ├── Patients Page
│       │   └── Table with links to details
│       ├── Patient Detail Page
│       │   └── Appointment history
│       └── Settings Page
│           ├── General Settings
│           ├── WhatsApp Status
│           ├── Integrations
│           └── Availability Hours
└── Root Redirect
```

---

## Data Flow

```
User Browser
    ↓
Next.js App Router
    ↓
Middleware (Auth Check)
    ↓
Page Component (Client/Server)
    ↓
useApi() Hook
    ↓
API Client Class
    ↓
Supabase Auth (JWT Token)
    ↓
Backend API
    ↓
Supabase Database
```

---

## Key Files by Purpose

### Authentication System
- `src/app/(auth)/login/page.tsx` - User login
- `src/app/(auth)/register/page.tsx` - Doctor registration
- `src/middleware.ts` - Route protection
- `src/lib/supabase.ts` - Auth client setup

### Appointment Management
- `src/app/(dashboard)/page.tsx` - Today's view
- `src/app/(dashboard)/agenda/page.tsx` - Calendar
- `src/components/agenda/CitaCard.tsx` - Appointment card
- `src/components/agenda/CalendarioFullCalendar.tsx` - Calendar widget
- `src/lib/api.ts` - API methods for appointments

### Patient Management
- `src/app/(dashboard)/pacientes/page.tsx` - Patient list
- `src/app/(dashboard)/pacientes/[id]/page.tsx` - Patient profile
- `src/lib/api.ts` - API methods for patients

### Settings
- `src/app/(dashboard)/configuracion/page.tsx` - All settings
- `src/components/coexistencia/BotStatusBadge.tsx` - Bot control
- `src/lib/api.ts` - Bot control methods

### Styling & UI
- `src/app/globals.css` - Global styles
- `tailwind.config.ts` - Theme colors
- `src/components/ui/*.tsx` - Reusable components

### Configuration
- `package.json` - Dependencies
- `tsconfig.json` - TypeScript config
- `next.config.js` - Next.js config
- `.env.local.example` - Environment template

---

## Development Workflow

### Adding a New Feature

1. **Create new page** in `src/app/(dashboard)/new-feature/page.tsx`
2. **Create components** in `src/components/new-feature/`
3. **Add API methods** in `src/lib/api.ts`
4. **Style with Tailwind** using utility classes
5. **Use TypeScript** for type safety
6. **Test** in development server

### File Naming Conventions

- **Pages**: `page.tsx` (not `index.tsx`)
- **Components**: PascalCase (e.g., `CitaCard.tsx`)
- **Types**: Defined in component files or `src/lib/supabase.ts`
- **Utilities**: kebab-case files (e.g., `format-date.ts`)

### Import Paths

All imports use `@/` alias pointing to `src/`:
```typescript
import { Button } from '@/components/ui/Button'
import { useApi } from '@/lib/api'
import type { Cita } from '@/lib/supabase'
```

---

## Build Output

When running `npm run build`:
- Compiled Next.js app in `.next/` directory
- Optimized JavaScript bundles
- Static files in `public/` directory
- Ready for deployment with `npm start`

---

## Deployment Files

- **Dockerfile** - Container image definition
- **.dockerignore** - Files to exclude from Docker build
- **vercel.json** (optional) - Vercel-specific configuration

For deployment instructions, see SETUP.md

---

## Documentation Map

| Document | Purpose | Audience |
|----------|---------|----------|
| README.md | Quick start & overview | Everyone |
| SETUP.md | Detailed setup with SQL | Developers |
| PROJECT_SUMMARY.md | Complete architecture | Architects |
| FILES.md | File index & structure | This file |

---

## Total Project Size

- **Source Code**: ~2,500 lines of TypeScript
- **Configuration**: ~200 lines
- **Documentation**: ~1,000 lines
- **Uncompressed**: ~196 KB
- **With node_modules**: ~400 MB (after `npm install`)

---

## Next Steps

1. Run `npm install` to install dependencies
2. Copy `.env.local.example` to `.env.local` and configure
3. Run `npm run dev` to start development server
4. Open http://localhost:3000 in browser
5. Follow SETUP.md for database configuration

For more details, see the documentation files in the project root.
