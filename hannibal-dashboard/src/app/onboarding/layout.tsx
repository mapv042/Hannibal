import React from 'react'
import { Logo } from '@/components/ui/Logo'

export const dynamic = 'force-dynamic'

export default function OnboardingLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div
      className="relative min-h-screen flex flex-col items-center py-10 px-4 overflow-hidden"
      style={{
        background: `radial-gradient(ellipse 60% 40% at 20% 0%, rgba(var(--primary-rgb-500), .10), transparent 60%),
                     radial-gradient(ellipse 60% 40% at 80% 100%, rgba(var(--secondary-rgb-500), .08), transparent 60%),
                     linear-gradient(180deg, #f9fafb, #eef1fa)`,
      }}
    >
      {/* Logo */}
      <div className="mb-8">
        <Logo size={30} />
      </div>

      {/* Content */}
      <div className="relative w-full max-w-5xl">
        {children}
      </div>

      <p className="text-xs text-gray-400 mt-8">Hannibal &copy; 2026</p>
    </div>
  )
}
