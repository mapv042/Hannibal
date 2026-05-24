import React from 'react'
import { Badge } from '@/components/ui/Badge'

interface StepHeaderProps {
  eyebrow?: string
  title: string
  subtitle?: string
}

export const StepHeader: React.FC<StepHeaderProps> = ({
  eyebrow,
  title,
  subtitle,
}) => {
  return (
    <div className="mb-7">
      {eyebrow && (
        <Badge variant="primary" className="mb-3.5">
          {eyebrow}
        </Badge>
      )}
      <h1 className="text-[26px] font-bold tracking-tight leading-tight text-gray-900">
        {title}
      </h1>
      {subtitle && (
        <p className="text-[15px] leading-relaxed text-gray-600 mt-2.5">
          {subtitle}
        </p>
      )}
    </div>
  )
}
