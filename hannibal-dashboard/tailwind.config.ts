import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // ── Brand world ────────────────────────────────────────────────
        // Named after what they are in the product, not their position on a
        // ramp. An institutional navy that reads as a medical practice's
        // letterhead, a single working blue, and paper-toned neutrals.
        navy: '#0B2545',
        'navy-deep': '#071A33',
        ink: '#16213D',
        accent: '#2952A3',
        'accent-bright': '#3D6BD1',
        slate: '#5B6B8C',
        'slate-light': '#8B96AD',
        line: '#E4E9F2',
        'off-white': '#F7F9FC',
        'brand-green': '#1E8A5F',

        // ── Ramp ───────────────────────────────────────────────────────
        // Same blue, expressed as a scale. Screens that predate the brand
        // tokens (dashboard, auth, legal) reference primary-* and land in the
        // new palette without being rewritten. 600 = accent, 900 = navy.
        primary: {
          50: '#f1f5fc',
          100: '#dee7f7',
          200: '#becfef',
          300: '#93b0e4',
          400: '#6089d6',
          500: '#3d6bd1',
          600: '#2952a3',
          700: '#1f3f80',
          800: '#16305f',
          900: '#0b2545',
        },
        // Kept only so pre-existing secondary-* usages resolve.
        secondary: {
          50: '#f1f5fc',
          100: '#dee7f7',
          200: '#becfef',
          300: '#93b0e4',
          400: '#6089d6',
          500: '#3d6bd1',
          600: '#2952a3',
          700: '#1f3f80',
          800: '#16305f',
          900: '#0b2545',
        },
        success: '#1e8a5f',
        warning: '#b7791f',
        error: '#c53030',
        info: '#2952a3',
      },
      fontFamily: {
        sans: ['var(--font-inter)', 'system-ui', 'sans-serif'],
        serif: ['var(--font-newsreader)', 'Georgia', 'serif'],
        mono: ['var(--font-jetbrains-mono)', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        // Depth strategy is borders. Shadows are reserved for the few things
        // that genuinely float above the page.
        xs: '0 1px 2px rgba(11, 37, 69, 0.04)',
        sm: '0 1px 2px rgba(11, 37, 69, 0.05)',
        base: '0 1px 3px rgba(11, 37, 69, 0.07)',
        md: '0 4px 12px rgba(11, 37, 69, 0.07)',
        lg: '0 20px 50px -20px rgba(11, 37, 69, 0.18)',
        float: '0 1px 2px rgba(11,37,69,0.04), 0 8px 24px rgba(11,37,69,0.10), 0 30px 60px -20px rgba(11,37,69,0.25)',
      },
      borderRadius: {
        // Editorial, not friendly: controls are nearly square, surfaces relax.
        sm: '3px',
        DEFAULT: '6px',
        md: '6px',
        lg: '10px',
        xl: '10px',
        '2xl': '12px',
        '3xl': '14px',
      },
      letterSpacing: {
        eyebrow: '2px',
      },
    },
  },
  plugins: [],
}

export default config
