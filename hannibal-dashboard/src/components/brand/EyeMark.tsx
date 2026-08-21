import React from 'react'

/** Feather strand endpoints, mirrored left/right. Ordered bottom → top. */
const BARBS: { d: string; cx: number; cy: number }[] = [
  { d: 'M45 112 Q30 108 18 98', cx: 18, cy: 98 },
  { d: 'M45 105 Q28 99 14 86', cx: 14, cy: 86 },
  { d: 'M45 96 Q26 88 12 72', cx: 12, cy: 72 },
  { d: 'M45 85 Q25 75 13 56', cx: 13, cy: 56 },
  { d: 'M45 72 Q26 60 16 40', cx: 16, cy: 40 },
  { d: 'M45 58 Q29 44 22 24', cx: 22, cy: 24 },
]

const MIRRORED: { d: string; cx: number; cy: number }[] = [
  { d: 'M45 112 Q60 108 72 98', cx: 72, cy: 98 },
  { d: 'M45 105 Q62 99 76 86', cx: 76, cy: 86 },
  { d: 'M45 96 Q64 88 78 72', cx: 78, cy: 72 },
  { d: 'M45 85 Q65 75 77 56', cx: 77, cy: 56 },
  { d: 'M45 72 Q64 60 74 40', cx: 74, cy: 40 },
  { d: 'M45 58 Q61 44 68 24', cx: 68, cy: 24 },
]

interface EyeMarkProps {
  /** Rendered height in px. Width follows the 3:4 ratio of the mark. */
  size?: number
  /** Feathers, stem and outer iris. */
  color?: string
  /** The eye's field — the ring inside the outer ellipse. */
  iris?: string
  /** The innermost dot. */
  pupil?: string
  /**
   * `full` draws all six barbs per side; `compact` drops to three, which is
   * what survives legibly below ~24px (avatar, footer, favicon-scale).
   */
  variant?: 'full' | 'compact'
  /** Slow opacity breathe on the iris. Only for the hero. */
  animate?: boolean
  className?: string
}

/**
 * The ArgosAI mark: a peacock feather's eye. Argos Panoptes was the giant with
 * a hundred eyes who never slept — the whole product promise in one image, and
 * the reason the assistant can answer at 2am. When Argos was killed his eyes
 * were set into the peacock's tail, which is the shape drawn here.
 */
export const EyeMark: React.FC<EyeMarkProps> = ({
  size = 26,
  color = '#2952A3',
  iris = '#F7F9FC',
  pupil = '#0B2545',
  variant = 'full',
  animate = false,
  className = '',
}) => {
  const barbs = variant === 'full' ? BARBS : BARBS.filter((_, i) => i % 2 === 0)
  const mirrored =
    variant === 'full' ? MIRRORED : MIRRORED.filter((_, i) => i % 2 === 0)
  const strands = [...barbs, ...mirrored]
  const dotR = variant === 'full' ? 2.2 : 3
  const strokeW = variant === 'full' ? 1.3 : 1.5

  return (
    <svg
      width={(size * 90) / 120}
      height={size}
      viewBox="0 0 90 120"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      <g stroke={color} strokeWidth={strokeW} opacity="0.5" fill="none">
        {strands.map((s) => (
          <path key={s.d} d={s.d} />
        ))}
      </g>
      <g fill={color} opacity="0.75">
        {strands.map((s) => (
          <circle key={`${s.cx}-${s.cy}`} cx={s.cx} cy={s.cy} r={dotR} />
        ))}
      </g>
      <path d="M45 118 L45 12" stroke={color} strokeWidth="2" />
      <ellipse
        cx="45"
        cy="32"
        rx="20"
        ry="25"
        fill={color}
        className={animate ? 'eye-breathe' : undefined}
      />
      <ellipse cx="45" cy="32" rx="11.5" ry="14.5" fill={iris} />
      <ellipse cx="45" cy="32" rx="4.5" ry="6" fill={pupil} />
    </svg>
  )
}

EyeMark.displayName = 'EyeMark'
