/**
 * Meta WhatsApp Embedded Signup launcher.
 *
 * Loads the Facebook JS SDK on demand and opens the Embedded Signup popup.
 * Two channels report back and BOTH are needed:
 *  - FB.login's callback returns a one-time authorization `code`
 *    (response_type: 'code' — the browser never sees an access token; the
 *    backend exchanges the code using the app secret).
 *  - A `message` event from facebook.com (type WA_EMBEDDED_SIGNUP, session
 *    info v3) reports the `phone_number_id` and `waba_id` the user connected.
 */

const SDK_URL = 'https://connect.facebook.net/en_US/sdk.js'
const GRAPH_VERSION = 'v21.0'
// How long to wait for the session-info message after the login code arrives.
const SESSION_INFO_TIMEOUT_MS = 5000

interface FBLoginResponse {
  authResponse?: { code?: string } | null
  status?: string
}

interface FBSdk {
  init(options: Record<string, unknown>): void
  login(
    callback: (response: FBLoginResponse) => void,
    options: Record<string, unknown>
  ): void
}

declare global {
  interface Window {
    FB?: FBSdk
    fbAsyncInit?: () => void
  }
}

export interface EmbeddedSignupResult {
  code: string
  phoneNumberId: string
  wabaId: string
}

export class EmbeddedSignupCancelledError extends Error {
  constructor() {
    super('Embedded Signup cancelled by the user')
    this.name = 'EmbeddedSignupCancelledError'
  }
}

let sdkPromise: Promise<FBSdk> | null = null

function loadFacebookSdk(appId: string): Promise<FBSdk> {
  if (sdkPromise) return sdkPromise

  sdkPromise = new Promise<FBSdk>((resolve, reject) => {
    if (window.FB) {
      resolve(window.FB)
      return
    }

    window.fbAsyncInit = () => {
      if (!window.FB) {
        reject(new Error('Facebook SDK loaded but window.FB is missing'))
        return
      }
      window.FB.init({
        appId,
        autoLogAppEvents: true,
        xfbml: false,
        version: GRAPH_VERSION,
      })
      resolve(window.FB)
    }

    const script = document.createElement('script')
    script.src = SDK_URL
    script.async = true
    script.defer = true
    script.crossOrigin = 'anonymous'
    script.onerror = () => {
      sdkPromise = null
      reject(new Error('No se pudo cargar el SDK de Facebook'))
    }
    document.head.appendChild(script)
  })

  return sdkPromise
}

/**
 * Opens the Embedded Signup popup and resolves with the code + ids the
 * backend needs. Rejects with EmbeddedSignupCancelledError when the user
 * closes/cancels the flow.
 *
 * `mode` 'coexistence' runs Meta's WhatsApp Business App onboarding flow
 * (number keeps working on the doctor's phone); 'new' runs the standard flow.
 */
export async function launchWhatsAppSignup(
  mode: 'coexistence' | 'new' = 'coexistence'
): Promise<EmbeddedSignupResult> {
  const appId = process.env.NEXT_PUBLIC_META_APP_ID
  const configId = process.env.NEXT_PUBLIC_META_ES_CONFIG_ID
  if (!appId || !configId) {
    throw new Error(
      'Faltan NEXT_PUBLIC_META_APP_ID / NEXT_PUBLIC_META_ES_CONFIG_ID en la configuración'
    )
  }

  const FB = await loadFacebookSdk(appId)

  return new Promise<EmbeddedSignupResult>((resolve, reject) => {
    let code: string | null = null
    let phoneNumberId: string | null = null
    let wabaId: string | null = null
    let settled = false
    let sessionInfoTimer: ReturnType<typeof setTimeout> | null = null

    const cleanup = () => {
      window.removeEventListener('message', onMessage)
      if (sessionInfoTimer) clearTimeout(sessionInfoTimer)
    }
    const settle = (fn: () => void) => {
      if (settled) return
      settled = true
      cleanup()
      fn()
    }
    const maybeResolve = () => {
      if (code && phoneNumberId && wabaId) {
        const result = { code, phoneNumberId, wabaId }
        settle(() => resolve(result))
      } else if (code && !sessionInfoTimer) {
        // Login finished but Meta's session-info message hasn't arrived (or
        // never will, e.g. the user stopped before connecting a number).
        sessionInfoTimer = setTimeout(() => {
          settle(() =>
            reject(
              new Error(
                'Meta no reportó el número conectado. Completa todos los pasos de la ventana de Meta e intenta de nuevo.'
              )
            )
          )
        }, SESSION_INFO_TIMEOUT_MS)
      }
    }

    const onMessage = (event: MessageEvent) => {
      if (!event.origin.endsWith('facebook.com')) return
      let data: any
      try {
        data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data
      } catch {
        return // unrelated non-JSON message
      }
      if (data?.type !== 'WA_EMBEDDED_SIGNUP') return

      if (data.event === 'FINISH' || data.event === 'FINISH_ONLY_WABA') {
        phoneNumberId = data.data?.phone_number_id ?? null
        wabaId = data.data?.waba_id ?? null
        maybeResolve()
      } else if (data.event === 'CANCEL') {
        settle(() => reject(new EmbeddedSignupCancelledError()))
      } else if (data.event === 'ERROR') {
        settle(() =>
          reject(
            new Error(data.data?.error_message || 'Error en el registro de Meta')
          )
        )
      }
    }

    window.addEventListener('message', onMessage)

    FB.login(
      (response) => {
        const authCode = response?.authResponse?.code
        if (authCode) {
          code = authCode
          maybeResolve()
        } else {
          settle(() => reject(new EmbeddedSignupCancelledError()))
        }
      },
      {
        config_id: configId,
        response_type: 'code',
        override_default_response_type: true,
        extras: {
          setup: {},
          sessionInfoVersion: '3',
          // Coexistence: connect the number the doctor already uses in the
          // WhatsApp Business app, keeping it active on their phone.
          ...(mode === 'coexistence'
            ? { featureType: 'whatsapp_business_app_onboarding' }
            : {}),
        },
      }
    )
  })
}
