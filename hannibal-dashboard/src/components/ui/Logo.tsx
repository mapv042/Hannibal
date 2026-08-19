import React from 'react'
import { EyeMark } from '@/components/brand/EyeMark'

interface LogoProps {
  size?: number
  withText?: boolean
  light?: boolean
  className?: string
}

/**
 * ArgosAI lockup — the feather-eye mark beside the wordmark, set in the same
 * serif as every headline so the brand and its voice are the same object.
 *
 * The wordmark stays "ArgosAI" verbatim: Google's OAuth branding review checks
 * that the consent screen's app name matches the one on the homepage, and this
 * component renders that name on the homepage, the legal pages and the panel.
 */
export const Logo: React.FC<LogoProps> = ({
  size = 28,
  withText = true,
  light = false,
  className = '',
}) => {
  return (
    <div className={`inline-flex items-center gap-2.5 ${className}`}>
      <EyeMark
        size={size * 0.95}
        variant={size < 26 ? 'compact' : 'full'}
        color={light ? '#6E93D6' : '#2952A3'}
        iris={light ? '#0B2545' : '#F7F9FC'}
        pupil={light ? '#6E93D6' : '#0B2545'}
      />
      {withText && (
        <span
          className={`font-serif font-semibold ${light ? 'text-white' : 'text-navy'}`}
          style={{ fontSize: size * 0.68, letterSpacing: '-0.01em' }}
        >
          ArgosAI
        </span>
      )}
    </div>
  )
}

Logo.displayName = 'Logo'
