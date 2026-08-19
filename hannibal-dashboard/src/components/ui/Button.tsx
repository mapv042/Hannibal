import React from 'react'

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost'
  size?: 'sm' | 'md' | 'lg'
  isLoading?: boolean
  children: React.ReactNode
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({
    variant = 'primary',
    size = 'md',
    isLoading = false,
    disabled,
    children,
    className = '',
    ...props
  }, ref) => {
    const baseStyles = 'inline-flex items-center justify-center gap-2 font-semibold rounded-sm transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-offset-2'

    // The primary brightens on hover rather than darkening. Secondary gains a
    // blue edge instead of a fill, so the two never compete.
    const variantStyles = {
      primary: 'bg-accent text-white hover:bg-accent-bright focus:ring-accent disabled:opacity-45 disabled:cursor-not-allowed',
      secondary: 'bg-white text-navy border border-line hover:border-accent hover:bg-off-white focus:ring-accent disabled:opacity-45 disabled:cursor-not-allowed',
      danger: 'bg-error text-white hover:bg-red-700 focus:ring-error disabled:opacity-45 disabled:cursor-not-allowed',
      ghost: 'text-slate hover:bg-off-white hover:text-navy focus:ring-slate-light disabled:opacity-45 disabled:cursor-not-allowed',
    }

    const sizeStyles = {
      sm: 'h-9 px-3.5 text-[13px]',
      md: 'h-11 px-5 text-sm',
      lg: 'h-[52px] px-7 text-[15px]',
    }

    return (
      <button
        ref={ref}
        disabled={disabled || isLoading}
        className={`${baseStyles} ${variantStyles[variant]} ${sizeStyles[size]} ${className}`}
        {...props}
      >
        {isLoading && (
          <svg
            className="w-4 h-4 mr-2 animate-spin"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
            />
          </svg>
        )}
        {children}
      </button>
    )
  }
)

Button.displayName = 'Button'
