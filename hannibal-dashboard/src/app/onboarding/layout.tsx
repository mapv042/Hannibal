'use client'

import React from 'react'
import { Heart } from 'lucide-react'

export default function OnboardingLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="min-h-screen bg-gradient-to-br from-primary-50 to-secondary-50 flex flex-col items-center py-8 px-4">
      {/* Logo */}
      <div className="flex items-center gap-3 mb-8">
        <div className="p-2 bg-white rounded-lg shadow-sm">
          <Heart className="w-6 h-6 text-primary-600" fill="currentColor" />
        </div>
        <h1 className="font-bold text-xl text-gray-900">Hannibal</h1>
      </div>

      {/* Content */}
      <div className="w-full max-w-2xl">
        {children}
      </div>

      <p className="text-xs text-gray-400 mt-8">Hannibal &copy; 2026</p>
    </div>
  )
}
