import { NextResponse } from 'next/server'
import { COOKIE_NAME, getExpectedToken } from './lib/auth'

// Everything except /login and /api/login requires a valid auth cookie.
// This runs before any page/route handler, so an unauthenticated request
// never reaches the code that queries Postgres and renders recruiter data.
const PUBLIC_PATHS = new Set(['/login', '/api/login'])

export async function middleware(request) {
  const { pathname } = request.nextUrl
  if (PUBLIC_PATHS.has(pathname)) {
    return NextResponse.next()
  }

  const token = request.cookies.get(COOKIE_NAME)?.value
  const expected = await getExpectedToken()
  if (token !== expected) {
    const url = request.nextUrl.clone()
    url.pathname = '/login'
    url.searchParams.set('from', pathname)
    return NextResponse.redirect(url)
  }

  return NextResponse.next()
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
}
