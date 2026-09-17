import { NextResponse } from 'next/server'
import { query } from '../../../../lib/db'

const OWNER = 'edisonmoy'
const REPO = 'fun-scripts'

function ghHeaders(token) {
  return {
    Authorization: `Bearer ${token}`,
    Accept: 'application/vnd.github+json',
  }
}

// Polled from the dashboard while a triggered run is in flight. Reports
// overall run status/conclusion plus per-step status from the job's step
// list, so the UI can render a live checklist without needing to parse
// raw Actions log text.
export async function GET(request, { params }) {
  const { runId } = await params
  const token = process.env.GITHUB_DISPATCH_TOKEN
  if (!token) {
    return NextResponse.json({ error: 'GITHUB_DISPATCH_TOKEN is not set' }, { status: 500 })
  }

  const [runRes, jobsRes] = await Promise.all([
    fetch(`https://api.github.com/repos/${OWNER}/${REPO}/actions/runs/${runId}`, {
      headers: ghHeaders(token),
    }),
    fetch(`https://api.github.com/repos/${OWNER}/${REPO}/actions/runs/${runId}/jobs`, {
      headers: ghHeaders(token),
    }),
  ])

  if (!runRes.ok) {
    return NextResponse.json({ error: `GitHub run lookup failed: ${runRes.status}` }, { status: 502 })
  }

  const run = await runRes.json()
  const jobs = jobsRes.ok ? await jobsRes.json() : { jobs: [] }

  if (run.status === 'completed') {
    // Only clear if it's still this run being tracked - avoids clobbering
    // a newer run_state.active_run_id set by a dispatch that happened
    // while this poll was in flight.
    await query(
      'UPDATE run_state SET active_run_id = NULL WHERE id = 1 AND active_run_id = $1',
      [runId]
    )
  }

  const steps = (jobs.jobs || []).flatMap((job) =>
    (job.steps || []).map((step) => ({
      name: step.name,
      status: step.status, // queued | in_progress | completed
      conclusion: step.conclusion, // success | failure | skipped | cancelled | null
    }))
  )

  return NextResponse.json({
    status: run.status, // queued | in_progress | completed
    conclusion: run.conclusion, // success | failure | ... | null while running
    htmlUrl: run.html_url,
    steps,
  })
}
