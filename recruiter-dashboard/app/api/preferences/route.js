import { NextResponse } from 'next/server'
import { query } from '../../../lib/db'
import { refreshTemplateDrafts } from '../../../lib/triage/sync'

export async function GET() {
  const { rows } = await query('SELECT * FROM preferences WHERE id = 1')
  return NextResponse.json({ preferences: rows[0] || null })
}

export async function PUT(request) {
  let body
  try {
    body = await request.json()
  } catch {
    return NextResponse.json({ error: 'invalid JSON body' }, { status: 400 })
  }

  const {
    target_areas = '',
    seniority = '',
    comp_floor = null,
    company_excludes = '',
    keep_warm_template = '',
    high_interest_template = '',
  } = body || {}

  let compFloorValue = null
  if (comp_floor !== null && comp_floor !== '' && comp_floor !== undefined) {
    const parsed = Number(comp_floor)
    if (!Number.isInteger(parsed)) {
      return NextResponse.json({ error: 'comp_floor must be an integer' }, { status: 400 })
    }
    compFloorValue = parsed
  }

  const { rows } = await query(
    `UPDATE preferences
     SET target_areas = $1,
         seniority = $2,
         comp_floor = $3,
         company_excludes = $4,
         keep_warm_template = $5,
         high_interest_template = $6,
         updated_at = now()
     WHERE id = 1
     RETURNING *`,
    [
      target_areas,
      seniority,
      compFloorValue,
      company_excludes,
      keep_warm_template,
      high_interest_template,
    ]
  )

  // Drafts still awaiting review pick up an edited template right away.
  await refreshTemplateDrafts(rows[0])

  return NextResponse.json({ preferences: rows[0] })
}
