/**
 * Password rules for email/password auth.
 *
 * Deliberately follows NIST SP 800-63B: a meaningful minimum length, a generous
 * maximum, and NO forced composition rules (an upper case letter plus a digit
 * plus a symbol). Composition rules push people toward `Password1!` and are
 * weaker in practice than simply allowing long passphrases.
 *
 * Keep MIN_PASSWORD_LENGTH at or above the "Minimum password length" configured
 * in Supabase Auth, otherwise the client accepts a password the server rejects.
 */
export const MIN_PASSWORD_LENGTH = 8

// Supabase hashes with bcrypt, which silently truncates past 72 bytes; refusing
// longer input is clearer than accepting a password only part of which counts.
export const MAX_PASSWORD_LENGTH = 72

/** Returns a Spanish error message, or null when the password is acceptable. */
export function validatePassword(password: string): string | null {
  if (password.length < MIN_PASSWORD_LENGTH) {
    return `La contraseña debe tener al menos ${MIN_PASSWORD_LENGTH} caracteres.`
  }
  if (password.length > MAX_PASSWORD_LENGTH) {
    return `La contraseña no puede exceder ${MAX_PASSWORD_LENGTH} caracteres.`
  }
  return null
}

/**
 * Maps a Supabase auth error to a message we're willing to show.
 *
 * Sign-in failures stay deliberately vague: Supabase already returns the same
 * "Invalid login credentials" for a wrong password and for an unknown address,
 * and we must not undo that — distinguishing them would let anyone enumerate
 * which doctors have accounts. Unconfirmed email is the one case worth naming,
 * because the user cannot act on it otherwise.
 */
export function authErrorMessage(message: string | undefined): string {
  const raw = (message || '').toLowerCase()

  if (raw.includes('invalid login credentials')) {
    return 'Correo o contraseña incorrectos.'
  }
  if (raw.includes('email not confirmed')) {
    return 'Confirma tu correo antes de iniciar sesión. Revisa tu bandeja de entrada.'
  }
  if (raw.includes('rate limit') || raw.includes('too many requests')) {
    return 'Demasiados intentos. Espera unos minutos e intenta de nuevo.'
  }
  if (raw.includes('weak password') || raw.includes('password should be')) {
    return `La contraseña es muy débil. Usa al menos ${MIN_PASSWORD_LENGTH} caracteres.`
  }
  return 'No pudimos completar la operación. Intenta de nuevo.'
}
