'use client'

import React, { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'

interface PasswordInputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
  helpText?: string
}

/**
 * Password field with a reveal toggle.
 *
 * The toggle matters for security rather than against it: without it people
 * pick shorter, easier-to-type passwords because they cannot check what they
 * typed. `autoComplete` is required from the caller (`current-password` when
 * signing in, `new-password` when setting one) so password managers offer the
 * right thing and don't overwrite a stored credential during a reset.
 */
export function PasswordInput({
  label,
  error,
  helpText,
  className = '',
  ...props
}: PasswordInputProps) {
  const [revealed, setRevealed] = useState(false)

  return (
    <div className="w-full">
      {label && (
        <label className="block text-[13px] text-slate mb-1.5">{label}</label>
      )}
      <div className="relative">
        <input
          type={revealed ? 'text' : 'password'}
          className={`input-field pr-11 ${error ? 'border-error focus:border-error' : ''} ${className}`}
          {...props}
        />
        <button
          type="button"
          onClick={() => setRevealed((v) => !v)}
          aria-label={revealed ? 'Ocultar contraseña' : 'Mostrar contraseña'}
          // Never a submit button, and skipped by keyboard tabbing so it does
          // not sit between the password field and the submit action.
          tabIndex={-1}
          className="absolute inset-y-0 right-0 px-3 flex items-center text-slate-light hover:text-slate transition-colors"
        >
          {revealed ? <EyeOff size={17} /> : <Eye size={17} />}
        </button>
      </div>
      {error && <p className="mt-1.5 text-[13px] text-error">{error}</p>}
      {helpText && !error && (
        <p className="mt-1.5 text-[13px] text-slate-light">{helpText}</p>
      )}
    </div>
  )
}
