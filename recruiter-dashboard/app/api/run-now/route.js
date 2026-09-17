import { NextResponse } from 'next/server'

const OWNER = 'edisonmoy'
const REPO = 'fun-scripts'
const WORKFLOW_FILE = 'gmail-recruiter-triage.yml'
const REF = 'master'

function ghHeaders(token) {
  return {
    Authorization: `Bearer ${token}`,
    Accept: 'application/vnd.github+json',
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

// The dispatch endpoint returns 204 with no run id, so we poll the
// workflow's run list briefly afterward to find the run it just created
// (matched by event + created_at at/after the dispatch time). If GitHub
// hasn't materialized the run yet after a few tries, we give up and the
// caller falls back to a plain "triggered" message without live tracking.
// Hobby-plan Vercel functions time out at 10s, so this budget (5 x 1s =
// 5s) plus the dispatch call itself needs to stay comfortably under that.
async function findNewRunId(token, dispatchedAt) {
  for (let attempt = 0; attempt < 5; attempt++) {
    await sleep(1000)
    const res = await fetch(
      `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW_FILE}/runs?event=workflow_dispatch&per_page=5`,
      { headers: ghHeaders(token) }
    )
    if (!res.ok) continue
    const data = await res.json()
    const match = (data.workflow_runs || []).find(
      (run) => new Date(run.created_at).getTime() >= dispatchedAt - 5000
    )
    if (match) return match.id
  }
  return null
}

export async function POST() {
  const token = process.env.GITHUB_DISPATCH_TOKEN
  if (!token) {
    return NextResponse.json({ error: 'GITHUB_DISPATCH_TOKEN is not set' }, { status: 500 })
  }

  const dispatchedAt = Date.now()
  const res = await fetch(
    `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
    {
      method: 'POST',
      headers: { ...ghHeaders(token), 'Content-Type': 'application/json' },
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

  const runId = await findNewRunId(token, dispatchedAt)
  return NextResponse.json({ ok: true, runId })
}
