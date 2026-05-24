import React from 'react'

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

export const StatusBadge: React.FC<{ estado: string; className?: string }> = ({
  estado,
  className = '',
}) => {
  const statusMap: Record<string, { variant: BadgeProps['variant']; label: string }> = {
    // Appointment statuses
    confirmed: { variant: 'success', label: 'Confirmada' },
    confirmada: { variant: 'success', label: 'Confirmada' },
    pending: { variant: 'warning', label: 'Pendiente' },
    pendiente: { variant: 'warning', label: 'Pendiente' },
    blocked: { variant: 'info', label: 'Bloqueada' },
    bloqueada: { variant: 'info', label: 'Bloqueada' },
    no_show: { variant: 'error', label: 'No asistió' },
    no_presentado: { variant: 'error', label: 'No asistió' },
    cancelled: { variant: 'error', label: 'Cancelada' },
    cancelada: { variant: 'error', label: 'Cancelada' },
    // Bot statuses
    active: { variant: 'success', label: 'Activo' },
    activo: { variant: 'success', label: 'Activo' },
    paused: { variant: 'warning', label: 'Pausado' },
    pausado: { variant: 'warning', label: 'Pausado' },
    inactive: { variant: 'error', label: 'Inactivo' },
    inactivo: { variant: 'error', label: 'Inactivo' },
  }

  const status = statusMap[estado] || { variant: 'default', label: estado }

  return (
    <Badge variant={status.variant} className={className}>
      {status.label}
    </Badge>
  )
}
