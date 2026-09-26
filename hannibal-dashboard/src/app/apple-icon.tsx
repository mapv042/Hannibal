import { renderAppIcon } from '@/lib/pwa/appIcon'

// iOS ignores the manifest's icons for "Add to Home Screen" and reads the
// apple-touch-icon link instead; 180px is the iPhone home-screen size.
export const size = { width: 180, height: 180 }
export const contentType = 'image/png'

export default function AppleIcon() {
  return renderAppIcon(180)
}
