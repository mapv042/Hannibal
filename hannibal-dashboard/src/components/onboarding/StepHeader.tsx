import React from 'react'

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
    <div className="mb-6">
      {eyebrow && <div className="eyebrow mb-2.5">{eyebrow}</div>}
      <h1 className="display text-[26px]">{title}</h1>
      {subtitle && (
        <p className="text-[15px] leading-relaxed text-slate mt-2.5">{subtitle}</p>
      )}
    </div>
  )
}
