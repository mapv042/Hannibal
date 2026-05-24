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
        primary: {
          50: '#eef1fa',
          100: '#d3dcf2',
          200: '#a0b3e6',
          300: '#6c87d9',
          400: '#3b5fc7',
          500: '#1535a3',
          600: '#092b82',
          700: '#061e5e',
          800: '#04143f',
          900: '#020a26',
        },
        secondary: {
          50: '#eef1fa',
          100: '#d3dcf2',
          200: '#a0b3e6',
          300: '#6c87d9',
          400: '#3b5fc7',
          500: '#2745b8',
          600: '#1535a3',
          700: '#061e5e',
          800: '#04143f',
          900: '#020a26',
        },
        success: '#10b981',
        warning: '#f59e0b',
        error: '#ef4444',
        info: '#0ea5e9',
      },
      fontFamily: {
        sans: ['var(--font-inter)', 'sans-serif'],
      },
      boxShadow: {
        xs: '0 1px 2px rgba(16, 24, 40, 0.04)',
        sm: '0 1px 3px rgba(16, 24, 40, 0.06), 0 1px 2px rgba(16, 24, 40, 0.04)',
        base: '0 1px 3px rgba(16, 24, 40, 0.08), 0 1px 2px rgba(16, 24, 40, 0.04)',
        md: '0 4px 12px rgba(16, 24, 40, 0.06), 0 2px 4px rgba(16, 24, 40, 0.04)',
        lg: '0 12px 32px rgba(16, 24, 40, 0.08), 0 4px 8px rgba(16, 24, 40, 0.04)',
      },
      borderRadius: {
        xl: '12px',
        '2xl': '16px',
      },
    },
  },
  plugins: [],
}

export default config
