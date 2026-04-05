// Re-export types (safe for both client and server)
export type { Office, Appointment, Patient, Doctor } from './types'

// Re-export browser client (safe for 'use client' components)
export { createBrowserSupabaseClient } from './browser'

// NOTE: Do NOT re-export server client here.
// Import it directly from '@/lib/supabase/server' in Server Components,
// Server Actions, and Route Handlers to avoid bundling next/headers
// into client code.
