import { NextResponse } from 'next/server'
import { query } from '../../../../lib/db'

// This route intentionally only allows the two transitions the dashboard UI
// can trigger. It must NOT accept arbitrary status values (e.g. 'sent' or
// 'drafted') - those are set by the triage job itself.
const ALLOWED_STATUSES = new Set(['approved_pending', 'rejected'])

export async function PATCH(request, context) {
  const { id } = await context.params
  if (!/^\d+$/.test(id)) {
    return NextResponse.json({ error: 'invalid id' }, { status: 400 })
  }

  let body
  try {
    body = await request.json()
  } catch {
    return NextResponse.json({ error: 'invalid JSON body' }, { status: 400 })
  }

  const { status } = body || {}
  if (!ALLOWED_STATUSES.has(status)) {
    return NextResponse.json(
      { error: `status must be one of: ${[...ALLOWED_STATUSES].join(', ')}` },
      { status: 400 }
    )
  }

  const { rows } = await query(
    `UPDATE triage_records
     SET status = $1, updated_at = now()
     WHERE id = $2
     RETURNING *`,
    [status, id]
  )

  if (rows.length === 0) {
    return NextResponse.json({ error: 'not found' }, { status: 404 })
  }

  return NextResponse.json({ record: rows[0] })
}
