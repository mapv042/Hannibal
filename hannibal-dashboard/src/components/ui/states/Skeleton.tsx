import React from 'react'

/**
 * Quiet loading placeholders — replaces the layout-shifting "Cargando…" text.
 * One animation, neutral surface, so loading feels like the page settling in
 * rather than something breaking.
 */
export const Skeleton: React.FC<{ className?: string }> = ({ className = '' }) => (
  <div className={`animate-pulse rounded-md bg-gray-200/70 ${className}`} />
)

Skeleton.displayName = 'Skeleton'

/** A stack of stat-card skeletons matching the dashboard grid. */
export const SkeletonStats: React.FC<{ count?: number }> = ({ count = 4 }) => (
  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
    {Array.from({ length: count }).map((_, i) => (
      <div key={i} className="card p-6 space-y-3">
        <div className="flex items-center justify-between">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-10 w-10 rounded-[10px]" />
        </div>
        <Skeleton className="h-8 w-12" />
      </div>
    ))}
  </div>
)

/** Stacked list-item skeletons (cards, appointment rows). */
export const SkeletonList: React.FC<{ count?: number }> = ({ count = 3 }) => (
  <div className="space-y-3">
    {Array.from({ length: count }).map((_, i) => (
      <div key={i} className="card p-4 space-y-3">
        <div className="flex items-start justify-between">
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-5 w-24 rounded-full" />
        </div>
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-3 w-28" />
      </div>
    ))}
  </div>
)

/** Table-row skeletons. */
export const SkeletonRows: React.FC<{ rows?: number; cols?: number }> = ({ rows = 5, cols = 5 }) => (
  <div className="space-y-3 py-2">
    {Array.from({ length: rows }).map((_, r) => (
      <div key={r} className="flex items-center gap-4">
        {Array.from({ length: cols }).map((_, c) => (
          <Skeleton key={c} className={`h-4 ${c === 0 ? 'w-40' : 'flex-1'}`} />
        ))}
      </div>
    ))}
  </div>
)
