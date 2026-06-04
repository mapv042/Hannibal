import React from 'react'

interface PageHeaderProps {
  title: string
  subtitle?: string
  /** Optional right-aligned actions (buttons, etc.). */
  actions?: React.ReactNode
}

/**
 * One page title to rule them all — kills the text-[28px] vs text-3xl split
 * and the meaningless "Panel" badge that sat on every screen.
 */
export const PageHeader: React.FC<PageHeaderProps> = ({ title, subtitle, actions }) => {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl sm:text-[28px] font-bold tracking-tight text-gray-900 leading-tight">
          {title}
        </h1>
        {subtitle && <p className="text-sm text-gray-500 mt-1">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2 flex-shrink-0">{actions}</div>}
    </div>
  )
}

PageHeader.displayName = 'PageHeader'
