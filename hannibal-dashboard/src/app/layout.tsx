import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'Hannibal - AI Assistant',
  description: 'Control panel to manage your WhatsApp assistant',
  keywords: ['hannibal', 'whatsapp', 'assistant', 'appointments', 'doctors'],
  authors: [{ name: 'Hannibal' }],
  openGraph: {
    title: 'Hannibal - AI Assistant',
    description: 'Control panel to manage your WhatsApp assistant',
    type: 'website',
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className={inter.variable}>
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </head>
      <body>{children}</body>
    </html>
  )
}
