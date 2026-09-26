import { NextResponse } from 'next/server'
import { runSyncBatch, SyncBusyError } from '../../../lib/triage/sync'

// A batch stops starting new threads after BATCH_BUDGET_MS, but one
// in-flight classification (with web research) can still run long, so give
// the function headroom beyond that.
export const maxDuration = 60

const THREAD_ID = /^[0-9a-f]{1,32}$/i

// Runs one batch of a sync; the dashboard keeps calling while `remaining`
// is above zero. `skip` is the thread ids that already failed earlier in
// the same sync.
export async function POST(request) {
  let body = {}
  try {
    body = await request.json()
  } catch {
    // no body is fine - a fresh sync
  }
  const skip = Array.isArray(body?.skip) ? body.skip : []
  if (skip.length > 500 || !skip.every((id) => typeof id === 'string' && THREAD_ID.test(id))) {
    return NextResponse.json({ error: 'invalid skip list' }, { status: 400 })
  }

  try {
    return NextResponse.json(await runSyncBatch({ skip }))
  } catch (err) {
    if (err instanceof SyncBusyError) {
      return NextResponse.json({ error: err.message }, { status: 409 })
    }
    console.error(`sync failed: ${err.message}`)
    return NextResponse.json({ error: 'Sync failed. Try again.' }, { status: 500 })
  }
}
