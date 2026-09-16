import { NextResponse } from 'next/server'

const OWNER = 'edisonmoy'
const REPO = 'fun-scripts'
const WORKFLOW_FILE = 'gmail-recruiter-triage.yml'
const REF = 'master'

// Manually triggers the daily triage GitHub Action instead of waiting for
// its cron schedule. Requires a token with `workflow` scope - the GitHub
// dispatch endpoint returns 204 with no body, so there's no run id to
// return here; the caller is pointed at the Actions tab to watch it.
export async function POST() {
  const token = process.env.GITHUB_DISPATCH_TOKEN
  if (!token) {
    return NextResponse.json({ error: 'GITHUB_DISPATCH_TOKEN is not set' }, { status: 500 })
  }

  const res = await fetch(
    `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/vnd.github+json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ ref: REF }),
    }
  )

  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    return NextResponse.json(
      { error: `GitHub dispatch failed: ${res.status} ${detail}` },
      { status: 502 }
    )
  }

  return NextResponse.json({ ok: true })
}
