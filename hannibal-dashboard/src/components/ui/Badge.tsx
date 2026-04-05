import React from 'react'

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: 'success' | 'warning' | 'error' | 'info' | 'default'
  children: React.ReactNode
}

export const Badge: React.FC<BadgeProps> = ({
  variant = 'default',
  className = '',
  children,
  ...props
}) => {
  const variantStyles = {
    success: 'badge-success',
    warning: 'badge-warning',
    error: 'badge-error',
    info: 'badge-info',
    default: 'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800',
  }

  return (
    <span
      className={`${variantStyles[variant]} ${className}`}
      {...props}
    >
      {children}
    </span>
  )
}

Badge.displayName = 'Badge'

export const StatusBadge: React.FC<{ estado: string; className?: string }> = ({
  estado,
  className = '',
}) => {
  const statusMap: Record<string, { variant: BadgeProps['variant']; label: string }> = {
    // Appointment statuses
    confirmed: { variant: 'success', label: 'Confirmed' },
    confirmada: { variant: 'success', label: 'Confirmed' },
    pending: { variant: 'warning', label: 'Pending' },
    pendiente: { variant: 'warning', label: 'Pending' },
    blocked: { variant: 'info', label: 'Blocked' },
    bloqueada: { variant: 'info', label: 'Blocked' },
    no_show: { variant: 'error', label: 'No Show' },
    no_presentado: { variant: 'error', label: 'No Show' },
    cancelled: { variant: 'error', label: 'Cancelled' },
    cancelada: { variant: 'error', label: 'Cancelled' },
    // Bot statuses
    active: { variant: 'success', label: 'Active' },
    activo: { variant: 'success', label: 'Active' },
    paused: { variant: 'warning', label: 'Paused' },
    pausado: { variant: 'warning', label: 'Paused' },
    inactive: { variant: 'error', label: 'Inactive' },
    inactivo: { variant: 'error', label: 'Inactive' },
  }

  const status = statusMap[estado] || { variant: 'default', label: estado }

  return (
    <Badge variant={status.variant} className={className}>
      {status.label}
    </Badge>
  )
}
