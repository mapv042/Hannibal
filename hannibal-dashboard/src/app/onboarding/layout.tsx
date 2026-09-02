import React from 'react'
import Link from 'next/link'
import { Logo } from '@/components/ui/Logo'

export const dynamic = 'force-dynamic'

export default function OnboardingLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div
      className="relative min-h-screen flex flex-col items-center py-10 px-4"
      style={{
        background:
          'radial-gradient(ellipse 800px 400px at 50% 0%, rgba(41,82,163,0.05), transparent), #fff',
      }}
    >
      <div className="mb-8">
        <Link href="/" aria-label="Argos — inicio">
          <Logo size={28} />
        </Link>
      </div>

      <div className="relative w-full max-w-5xl">{children}</div>

      <p className="text-xs text-slate-light mt-8">Argos &copy; 2026</p>
    </div>
  )
}
