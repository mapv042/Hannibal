import type { MetadataRoute } from 'next'
import { APP_ICON_BACKGROUND } from '@/lib/pwa/appIcon'

// Installing from the browser ("Agregar a pantalla de inicio" / "Instalar app")
// opens the panel standalone, without the browser's chrome. start_url is the
// panel: a signed-out user is sent to /login by the middleware from there.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'Argos',
    short_name: 'Argos',
    description: 'Panel de tu asistente de WhatsApp',
    lang: 'es-MX',
    start_url: '/dashboard',
    scope: '/',
    display: 'standalone',
    orientation: 'portrait',
    background_color: APP_ICON_BACKGROUND,
    theme_color: '#F7F9FC',
    icons: [
      { src: '/icon/192', sizes: '192x192', type: 'image/png', purpose: 'any' },
      { src: '/icon/512', sizes: '512x512', type: 'image/png', purpose: 'any' },
      { src: '/icon/512', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
    ],
  }
}
