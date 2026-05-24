import React from 'react'

interface ProgressBarProps {
  currentStep: number
  totalSteps: number
  title?: string
}

export const ProgressBar: React.FC<ProgressBarProps> = ({
  currentStep,
  totalSteps,
  title,
}) => {
  const progress = Math.round((currentStep / totalSteps) * 100)

  return (
    <div className="mb-8">
      <div className="flex justify-between items-baseline mb-2">
        <span className="text-sm font-semibold text-gray-700">
          Paso {currentStep} de {totalSteps}
          {title ? ` — ${title}` : ''}
        </span>
        <span className="text-sm text-gray-500 tabular-nums">{progress}%</span>
      </div>
      <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden">
        <div
          className="h-full bg-primary-500 rounded-full transition-all duration-500 ease-out"
          style={{ width: `${progress}%` }}
        />
      </div>
      {/* Step dots */}
      <div className="flex items-center gap-1.5 mt-4 justify-center">
        {Array.from({ length: totalSteps }).map((_, i) => {
          const reached = i < currentStep
          const isCurrent = i === currentStep - 1
          return (
            <div
              key={i}
              className={`h-1.5 rounded-full transition-all duration-300 ${
                reached ? 'bg-primary-500' : 'bg-gray-200'
              } ${isCurrent ? 'w-[18px]' : 'w-1.5'}`}
            />
          )
        })}
      </div>
    </div>
  )
}
