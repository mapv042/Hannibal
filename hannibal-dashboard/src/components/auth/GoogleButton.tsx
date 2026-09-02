'use client'

import React from 'react'
import { GoogleGlyph } from '@/components/brand/GoogleGlyph'

interface GoogleButtonProps {
  onClick: () => void
  disabled?: boolean
  label: string
}

export function GoogleButton({ onClick, disabled, label }: GoogleButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="w-full h-12 flex items-center justify-center gap-3 border border-line rounded-md bg-white hover:border-accent hover:bg-off-white transition-colors disabled:opacity-45 disabled:cursor-not-allowed"
    >
      <GoogleGlyph className="w-[18px] h-[18px]" />
      <span className="text-sm font-semibold text-navy">{label}</span>
    </button>
  )
}

/** "o" rule used to separate the Google button from the email/password form. */
export function AuthDivider() {
  return (
    <div className="relative">
      <div className="absolute inset-0 flex items-center" aria-hidden="true">
        <div className="w-full border-t border-line" />
      </div>
      <div className="relative flex justify-center">
        <span className="bg-white px-3 text-[12px] text-slate-light">o</span>
      </div>
    </div>
  )
}
