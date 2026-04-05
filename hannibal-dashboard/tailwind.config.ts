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
          50: '#f0f9f7',
          100: '#e0f3ef',
          200: '#c1e7df',
          300: '#a1dccf',
          400: '#6ec9b0',
          500: '#2ab89a',
          600: '#1d9a82',
          700: '#1a7d6e',
          800: '#166259',
          900: '#134d48',
        },
        secondary: {
          50: '#f0faf9',
          100: '#e1f5f3',
          200: '#c3ebe7',
          300: '#a4e0db',
          400: '#67cab4',
          500: '#2ab58d',
          600: '#1f9570',
          700: '#1a755a',
          800: '#155545',
          900: '#113639',
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
        sm: '0 1px 2px 0 rgba(0, 0, 0, 0.05)',
        base: '0 1px 3px 0 rgba(0, 0, 0, 0.1)',
        md: '0 4px 6px -1px rgba(0, 0, 0, 0.1)',
        lg: '0 10px 15px -3px rgba(0, 0, 0, 0.1)',
      },
    },
  },
  plugins: [],
}

export default config
