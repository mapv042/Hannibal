import type { Metadata } from 'next'
import { Inter, Newsreader, JetBrains_Mono } from 'next/font/google'
import './globals.css'

// Inter carries the interface: labels, inputs, body. It disappears, which is
// what a control should do.
const inter = Inter({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-inter',
  display: 'swap',
})

// Newsreader carries every headline. A practice's voice is written, not
// shipped — the serif is the whole reason the product doesn't read like a SaaS
// dashboard. The italic is load-bearing: it's how emphasis is expressed.
const newsreader = Newsreader({
  subsets: ['latin'],
  weight: ['500', '600', '700'],
  style: ['normal', 'italic'],
  variable: '--font-newsreader',
  display: 'swap',
  // Newsreader isn't in Next's font-metrics table, so it can't synthesize a
  // size-matched fallback and warns on every build. Georgia is close enough in
  // x-height that the swap doesn't jump.
  adjustFontFallback: false,
  fallback: ['Georgia', 'Times New Roman', 'serif'],
})

// Mono is for eyebrows, step numbers and anything that behaves like a
// specimen label — small, spaced, uppercase.
const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  weight: ['400', '500'],
  variable: '--font-jetbrains-mono',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'Argos - AI Assistant',
  description: 'Control panel to manage your WhatsApp assistant',
  keywords: ['argos', 'whatsapp', 'assistant', 'appointments', 'doctors'],
  authors: [{ name: 'Argos' }],
  openGraph: {
    title: 'Argos - AI Assistant',
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
    <html
      lang="es-MX"
      className={`${inter.variable} ${newsreader.variable} ${jetbrainsMono.variable}`}
    >
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <meta name="facebook-domain-verification" content="4bcg78qx5hyxjvhml2lf3gl9qm4s2e" />
      </head>
      <body>{children}</body>
    </html>
  )
}
