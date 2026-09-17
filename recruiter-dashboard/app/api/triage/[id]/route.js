import { NextResponse } from 'next/server'
import { query } from '../../../../lib/db'

// This route intentionally only allows the transitions the dashboard UI can
// trigger. It must NOT accept 'sent' - that's set by the triage job itself
// once it actually sends the Gmail draft. 'drafted' is allowed so a
// dashboard-approved (but not yet sent) row can be un-approved via
// "Cancel send".
const ALLOWED_STATUSES = new Set(['approved_pending', 'rejected', 'drafted'])

// Lets the dashboard reclassify a record (e.g. "actually this looks more
// serious than keep_warm") - a manual correction, independent of status.
const ALLOWED_CATEGORIES = new Set(['ignore', 'keep_warm', 'high_interest'])

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

  const { status, category } = body || {}
  if (status === undefined && category === undefined) {
    return NextResponse.json({ error: 'must provide status and/or category' }, { status: 400 })
  }
  if (status !== undefined && !ALLOWED_STATUSES.has(status)) {
    return NextResponse.json(
      { error: `status must be one of: ${[...ALLOWED_STATUSES].join(', ')}` },
      { status: 400 }
    )
  }
  if (category !== undefined && !ALLOWED_CATEGORIES.has(category)) {
    return NextResponse.json(
      { error: `category must be one of: ${[...ALLOWED_CATEGORIES].join(', ')}` },
      { status: 400 }
    )
  }

  const sets = ['updated_at = now()']
  const params = []
  if (status !== undefined) {
    params.push(status)
    sets.push(`status = $${params.length}`)
  }
  if (category !== undefined) {
    params.push(category)
    sets.push(`category = $${params.length}`)
  }
  params.push(id)

  const { rows } = await query(
    `UPDATE triage_records SET ${sets.join(', ')} WHERE id = $${params.length} RETURNING *`,
    params
  )

  if (rows.length === 0) {
    return NextResponse.json({ error: 'not found' }, { status: 404 })
  }

  return NextResponse.json({ record: rows[0] })
}
