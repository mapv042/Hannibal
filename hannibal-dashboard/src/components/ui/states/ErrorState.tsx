import React from 'react'
import { AlertTriangle, RotateCw } from 'lucide-react'

interface ErrorStateProps {
  title?: string
  description?: string
  /** When provided, shows a "Reintentar" button. */
  onRetry?: () => void
  className?: string
}

/**
 * The state the app was missing entirely: a failed request now SAYS so,
 * instead of looking like an empty result. Critical for a scheduling tool —
 * "no appointments" and "couldn't load" must never look the same.
 */
export const ErrorState: React.FC<ErrorStateProps> = ({
  title = 'No pudimos cargar la información',
  description = 'Revisa tu conexión e inténtalo de nuevo.',
  onRetry,
  className = '',
}) => {
  return (
    <div className={`text-center py-12 px-4 ${className}`}>
      <div className="w-12 h-12 rounded-xl bg-red-50 flex items-center justify-center mx-auto mb-4">
        <AlertTriangle size={24} className="text-error" />
      </div>
      <p className="text-sm font-medium text-gray-900">{title}</p>
      <p className="text-sm text-gray-500 mt-1 max-w-sm mx-auto">{description}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-5 inline-flex items-center gap-2 px-4 h-10 rounded-xl text-sm font-semibold text-gray-800 border border-gray-300 bg-white shadow-xs hover:bg-gray-100 transition-colors"
        >
          <RotateCw size={16} />
          Reintentar
        </button>
      )}
    </div>
  )
}

ErrorState.displayName = 'ErrorState'
