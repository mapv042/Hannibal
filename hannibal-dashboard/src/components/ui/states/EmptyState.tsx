import React from 'react'
import type { LucideIcon } from 'lucide-react'

interface EmptyStateProps {
  icon?: LucideIcon
  title: string
  description?: string
  /** Optional CTA (e.g. a Button). */
  action?: React.ReactNode
  className?: string
}

/**
 * "Nothing here yet" — distinct from an error. Use when a request succeeded
 * but returned no rows.
 */
export const EmptyState: React.FC<EmptyStateProps> = ({
  icon: Icon,
  title,
  description,
  action,
  className = '',
}) => {
  return (
    <div className={`text-center py-12 px-4 ${className}`}>
      {Icon && (
        <div className="w-12 h-12 rounded-xl bg-gray-100 flex items-center justify-center mx-auto mb-4">
          <Icon size={24} className="text-gray-400" />
        </div>
      )}
      <p className="text-sm font-medium text-gray-900">{title}</p>
      {description && <p className="text-sm text-gray-500 mt-1 max-w-sm mx-auto">{description}</p>}
      {action && <div className="mt-5 flex justify-center">{action}</div>}
    </div>
  )
}

EmptyState.displayName = 'EmptyState'
