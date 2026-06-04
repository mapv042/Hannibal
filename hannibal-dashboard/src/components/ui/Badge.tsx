import React from 'react'
import { getStatus, TONE_BADGE } from '@/lib/status'

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: 'success' | 'warning' | 'error' | 'info' | 'primary' | 'default'
  dot?: boolean
  children: React.ReactNode
}

const dotColors: Record<NonNullable<BadgeProps['variant']>, string> = {
  success: 'bg-success',
  warning: 'bg-warning',
  error: 'bg-error',
  info: 'bg-info',
  primary: 'bg-primary-500',
  default: 'bg-gray-400',
}

export const Badge: React.FC<BadgeProps> = ({
  variant = 'default',
  dot = false,
  className = '',
  children,
  ...props
}) => {
  const variantStyles = {
    success: 'badge-success',
    warning: 'badge-warning',
    error: 'badge-error',
    info: 'badge-info',
    primary: 'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-primary-50 text-primary-700',
    default: 'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-700',
  }

  return (
    <span
      className={`${variantStyles[variant]} ${dot ? 'gap-1.5' : ''} ${className}`}
      {...props}
    >
      {dot && (
        <span className={`w-1.5 h-1.5 rounded-full ${dotColors[variant]}`} />
      )}
      {children}
    </span>
  )
}

Badge.displayName = 'Badge'

/**
 * Status pill driven by the single status source of truth (lib/status.ts).
 * Pairs an icon with the label so status is never communicated by colour
 * alone (accessibility) and never falls through to an undefined style.
 */
export const StatusBadge: React.FC<{ estado: string; className?: string }> = ({
  estado,
  className = '',
}) => {
  const { label, tone, icon: Icon } = getStatus(estado)

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${TONE_BADGE[tone]} ${className}`}
    >
      <Icon size={12} strokeWidth={2.4} aria-hidden="true" />
      {label}
    </span>
  )
}
