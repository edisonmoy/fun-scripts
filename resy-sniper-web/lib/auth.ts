export const SESSION_COOKIE = "resy_session";

function toHex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function hmac(secret: string, message: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message));
  return toHex(sig);
}

// The valid session cookie value is a fixed HMAC of a constant string,
// keyed by AUTH_SECRET (distinct from ADMIN_PASSWORD - the password only
// gates issuing this token at login, it's never itself stored in a
// cookie). Edge-runtime-compatible (Web Crypto only, no Buffer) since
// middleware verifies it.
export async function sessionToken(): Promise<string> {
  const secret = process.env.AUTH_SECRET;
  if (!secret) throw new Error("AUTH_SECRET is not set");
  return hmac(secret, "resy-sniper-admin");
}

export async function isValidSession(cookieValue: string | undefined): Promise<boolean> {
  if (!cookieValue) return false;
  const expected = await sessionToken();
  return cookieValue === expected;
}
