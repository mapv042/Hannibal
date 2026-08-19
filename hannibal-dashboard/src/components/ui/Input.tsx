import React from 'react'

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
  helpText?: string
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, helpText, className = '', ...props }, ref) => {
    return (
      <div className="w-full">
        {label && (
          <label className="block text-[13px] text-slate mb-1.5">
            {label}
          </label>
        )}
        <input
          ref={ref}
          className={`input-field ${error ? 'border-error focus:border-error' : ''} ${className}`}
          {...props}
        />
        {error && (
          <p className="mt-1.5 text-[13px] text-error">{error}</p>
        )}
        {helpText && !error && (
          <p className="mt-1.5 text-[13px] text-slate-light">{helpText}</p>
        )}
      </div>
    )
  }
)

Input.displayName = 'Input'
