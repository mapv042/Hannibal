import React from 'react'

interface LogoProps {
  size?: number
  withText?: boolean
  className?: string
}

/**
 * Hannibal brand mark — rounded teal→green gradient tile with a stylized
 * "h" / chat-tail glyph. Matches the Claude Design reference.
 */
export const Logo: React.FC<LogoProps> = ({
  size = 28,
  withText = true,
  className = '',
}) => {
  return (
    <div className={`inline-flex items-center gap-2.5 ${className}`}>
      <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
        <defs>
          <linearGradient
            id="han-logo-g"
            x1="0"
            y1="0"
            x2="32"
            y2="32"
            gradientUnits="userSpaceOnUse"
          >
            <stop offset="0" stopColor="#1535a3" />
            <stop offset="1" stopColor="#092b82" />
          </linearGradient>
        </defs>
        <rect x="2" y="2" width="28" height="28" rx="8" fill="url(#han-logo-g)" />
        <path
          d="M10 9 L10 23 M10 16 Q10 13 13 13 L17 13 Q20 13 20 16 L20 22 L23 25"
          stroke="#fff"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
          fill="none"
        />
      </svg>
      {withText && (
        <span
          className="font-bold text-gray-900"
          style={{ fontSize: size * 0.65, letterSpacing: '-0.02em' }}
        >
          Hannibal
        </span>
      )}
    </div>
  )
}

Logo.displayName = 'Logo'
