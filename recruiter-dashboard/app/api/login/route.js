import { NextResponse } from 'next/server'
import { COOKIE_NAME, MAX_AGE, getExpectedToken, isValidPassword } from '../../../lib/auth'

export async function POST(request) {
  const body = await request.json().catch(() => ({}))
  const ok = await isValidPassword(body.password)
  if (!ok) {
    return NextResponse.json({ error: 'invalid password' }, { status: 401 })
  }

  const token = await getExpectedToken()
  const response = NextResponse.json({ ok: true })
  response.cookies.set(COOKIE_NAME, token, {
    httpOnly: true,
    secure: true,
    sameSite: 'lax',
    maxAge: MAX_AGE,
    path: '/',
  })
  return response
}
