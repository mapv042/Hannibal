import { ImageResponse } from 'next/og'
import { EyeMark } from '@/components/brand/EyeMark'

export const APP_ICON_BACKGROUND = '#0B2545'

/**
 * The home-screen icon: the feather-eye on the navy field, in the same light
 * variant the Logo uses on dark backgrounds.
 *
 * Drawn full-bleed and square — iOS and Android apply their own corner mask,
 * and a pre-rounded icon ends up with a navy halo inside theirs. The mark sits
 * at 60% of the height so it survives Android's maskable safe zone (the
 * centered circle of 80% diameter) whatever shape the launcher cuts.
 */
export function renderAppIcon(size: number): ImageResponse {
  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: APP_ICON_BACKGROUND,
        }}
      >
        <EyeMark
          size={Math.round(size * 0.6)}
          variant={size < 64 ? 'compact' : 'full'}
          color="#6E93D6"
          iris={APP_ICON_BACKGROUND}
          pupil="#6E93D6"
        />
      </div>
    ),
    { width: size, height: size }
  )
}
