// Simple shared-password auth for a single-user personal tool. No user
// table, no session store - the auth cookie is just a fixed HMAC digest
// (keyed by DASHBOARD_AUTH_SECRET) of a constant string, so it never
// encodes the password itself and can't be forged without the secret.
// Uses Web Crypto (global `crypto.subtle`) rather than `node:crypto` so the
// exact same code works in both the Node.js API route and the (by default
// Edge-runtime) middleware.

export const COOKIE_NAME = 'dashboard_auth'
export const MAX_AGE = 60 * 60 * 24 * 30 // 30 days

function toHex(buffer) {
  return Array.from(new Uint8Array(buffer))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

async function hmac(secret, message) {
  const key = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  )
  const signature = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(message))
  return toHex(signature)
}

export async function getExpectedToken() {
  const secret = process.env.DASHBOARD_AUTH_SECRET
  if (!secret) throw new Error('DASHBOARD_AUTH_SECRET is not set')
  return hmac(secret, 'dashboard-authenticated')
}

// Compares HMAC digests of the candidate/expected password (fixed-length
// hex strings) rather than the raw strings - avoids leaking timing
// information tied to the plaintext password's length/content without
// pulling in a password-hashing dependency for a single-user tool.
export async function isValidPassword(candidate) {
  const expected = process.env.DASHBOARD_PASSWORD
  if (!expected) throw new Error('DASHBOARD_PASSWORD is not set')
  const [a, b] = await Promise.all([
    hmac('password-check', String(candidate ?? '')),
    hmac('password-check', expected),
  ])
  return a === b
}
