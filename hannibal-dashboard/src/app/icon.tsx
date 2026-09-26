import { renderAppIcon } from '@/lib/pwa/appIcon'

// Served as /icon/<id>. 32 is the browser-tab favicon; 192 and 512 are the
// sizes the web app manifest references (Android's install prompt needs both).
const SIZES = [32, 192, 512]

export function generateImageMetadata() {
  return SIZES.map((size) => ({
    id: String(size),
    size: { width: size, height: size },
    contentType: 'image/png',
  }))
}

export default function Icon({ id }: { id: string }) {
  return renderAppIcon(Number(id))
}
