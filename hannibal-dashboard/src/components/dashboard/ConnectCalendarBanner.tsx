'use client'

import React, { useEffect, useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { CalendarPlus, X } from 'lucide-react'

/**
 * Nudge for practices that finished onboarding without connecting Google
 * Calendar — the step is skippable ("Omitir por ahora"), and someone who signed
 * up with email/password never had a Google account in hand at that moment, so
 * they are the most likely to have skipped it.
 *
 * Shown for any office without a token rather than only for password accounts:
 * a Google sign-in is a different OAuth grant with different scopes than
 * Calendar access, so signing in with Google says nothing about whether the
 * calendar is connected, and those users can skip the step just as easily.
 *
 * Dismissal is per office and local to the browser. Settings keeps the real
 * connect control, so losing this banner never blocks anyone.
 */
const dismissKey = (officeId: string) => `gcal_banner_dismissed:${officeId}`

interface ConnectCalendarBannerProps {
  officeId: string
  connected: boolean
}

export function ConnectCalendarBanner({ officeId, connected }: ConnectCalendarBannerProps) {
  const [dismissed, setDismissed] = useState(true) // assume dismissed until read
  const pathname = usePathname()

  useEffect(() => {
    try {
      setDismissed(localStorage.getItem(dismissKey(officeId)) === '1')
    } catch {
      // Private windows and blocked site data throw on access; showing the
      // banner is the safe fallback.
      setDismissed(false)
    }
  }, [officeId])

  const handleDismiss = () => {
    setDismissed(true)
    try {
      localStorage.setItem(dismissKey(officeId), '1')
    } catch {
      // Dismissal just won't persist; not worth surfacing.
    }
  }

  // Settings already renders the full Google Calendar card — no need to nag
  // someone who is looking straight at the control.
  if (connected || dismissed || pathname.startsWith('/dashboard/settings')) {
    return null
  }

  return (
    <div className="mb-6 flex items-start gap-3 rounded-xl border border-primary-100 bg-primary-50 p-4">
      <div className="mt-0.5 flex-shrink-0">
        <CalendarPlus size={18} className="text-primary-700" />
      </div>

      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-gray-900">
          Conecta tu Google Calendar
        </p>
        <p className="mt-1 text-[13px] text-gray-600 leading-relaxed">
          El asistente revisa tu calendario antes de ofrecer un horario, así no agenda encima de
          algo que ya tenías. Sin conectarlo, solo considera las citas creadas aquí.
        </p>
        <Link
          href="/dashboard/settings"
          className="mt-2.5 inline-block text-[13px] font-semibold text-primary-700 hover:underline"
        >
          Conectar ahora
        </Link>
      </div>

      <button
        type="button"
        onClick={handleDismiss}
        aria-label="Ocultar aviso"
        className="flex-shrink-0 p-1 text-gray-400 hover:text-gray-600 transition-colors"
      >
        <X size={16} />
      </button>
    </div>
  )
}
