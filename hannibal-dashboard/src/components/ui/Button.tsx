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
    const baseStyles = 'inline-flex items-center justify-center gap-2 font-semibold tracking-tight transition-all duration-150 rounded-xl focus:outline-none focus:ring-2 focus:ring-offset-2'

    const variantStyles = {
      primary: 'bg-primary-600 text-white shadow-[0_4px_12px_rgba(var(--primary-rgb-600),0.22)] hover:bg-primary-700 hover:shadow-[0_6px_20px_rgba(var(--primary-rgb-600),0.35)] focus:ring-primary-500 disabled:opacity-50 disabled:shadow-none disabled:cursor-not-allowed',
      secondary: 'bg-white text-gray-800 border border-gray-300 shadow-xs hover:bg-gray-100 focus:ring-gray-400 disabled:opacity-50 disabled:cursor-not-allowed',
      danger: 'bg-error text-white shadow-sm hover:bg-red-600 focus:ring-red-500 disabled:opacity-50 disabled:cursor-not-allowed',
      ghost: 'text-gray-700 hover:bg-gray-100 focus:ring-gray-400 disabled:opacity-50 disabled:cursor-not-allowed',
    }

    const sizeStyles = {
      sm: 'h-8 px-3 text-sm',
      md: 'h-10 px-4 text-sm',
      lg: 'h-12 px-6 text-[15px]',
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
