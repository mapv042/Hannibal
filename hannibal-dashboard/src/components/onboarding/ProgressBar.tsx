import React from 'react'

interface ProgressBarProps {
  currentStep: number
  totalSteps: number
  title?: string
}

/**
 * Segmented progress: one bar per step, filled as you pass it.
 *
 * A percentage tells a doctor mid-setup nothing actionable — "how many screens
 * are left" does, and the segments answer it at a glance without being read.
 * The step name stays because knowing the next screen is "Horarios" is what
 * makes someone finish rather than abandon.
 */
export const ProgressBar: React.FC<ProgressBarProps> = ({
  currentStep,
  totalSteps,
  title,
}) => {
  return (
    <div className="mb-7">
      <div
        className="flex gap-1.5 mb-3"
        role="progressbar"
        aria-valuenow={currentStep}
        aria-valuemin={1}
        aria-valuemax={totalSteps}
        aria-label={`Paso ${currentStep} de ${totalSteps}`}
      >
        {Array.from({ length: totalSteps }).map((_, i) => (
          <div
            key={i}
            className={`flex-1 h-[3px] rounded-sm transition-colors duration-300 ${
              i < currentStep ? 'bg-accent' : 'bg-line'
            }`}
          />
        ))}
      </div>
      <div className="eyebrow">
        Paso {currentStep} de {totalSteps}
        {title ? ` · ${title}` : ''}
      </div>
    </div>
  )
}
