import { NextResponse } from 'next/server'
import { query } from '../../../lib/db'

const AUTONOMY_VALUES = new Set(['draft_only', 'auto_send'])

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
    autonomy_keep_warm,
    autonomy_high_interest,
    keep_warm_auto_send_max_fit = null,
    high_interest_auto_send_min_fit = null,
    keep_warm_template = '',
    tone_notes = '',
  } = body || {}

  if (!AUTONOMY_VALUES.has(autonomy_keep_warm)) {
    return NextResponse.json(
      { error: `autonomy_keep_warm must be one of: ${[...AUTONOMY_VALUES].join(', ')}` },
      { status: 400 }
    )
  }
  if (!AUTONOMY_VALUES.has(autonomy_high_interest)) {
    return NextResponse.json(
      { error: `autonomy_high_interest must be one of: ${[...AUTONOMY_VALUES].join(', ')}` },
      { status: 400 }
    )
  }

  let compFloorValue = null
  if (comp_floor !== null && comp_floor !== '' && comp_floor !== undefined) {
    const parsed = Number(comp_floor)
    if (!Number.isInteger(parsed)) {
      return NextResponse.json({ error: 'comp_floor must be an integer' }, { status: 400 })
    }
    compFloorValue = parsed
  }

  function parseFitThreshold(value, fieldName) {
    if (value === null || value === '' || value === undefined) return null
    const parsed = Number(value)
    if (!Number.isInteger(parsed) || parsed < 0 || parsed > 100) {
      throw new Error(`${fieldName} must be an integer between 0 and 100`)
    }
    return parsed
  }

  let keepWarmThresholdValue
  let highInterestThresholdValue
  try {
    keepWarmThresholdValue = parseFitThreshold(
      keep_warm_auto_send_max_fit,
      'keep_warm_auto_send_max_fit'
    )
    highInterestThresholdValue = parseFitThreshold(
      high_interest_auto_send_min_fit,
      'high_interest_auto_send_min_fit'
    )
  } catch (err) {
    return NextResponse.json({ error: err.message }, { status: 400 })
  }

  const { rows } = await query(
    `UPDATE preferences
     SET target_areas = $1,
         seniority = $2,
         comp_floor = $3,
         company_excludes = $4,
         autonomy_keep_warm = $5,
         autonomy_high_interest = $6,
         tone_notes = $7,
         keep_warm_auto_send_max_fit = $8,
         high_interest_auto_send_min_fit = $9,
         keep_warm_template = $10,
         updated_at = now()
     WHERE id = 1
     RETURNING *`,
    [
      target_areas,
      seniority,
      compFloorValue,
      company_excludes,
      autonomy_keep_warm,
      autonomy_high_interest,
      tone_notes,
      keepWarmThresholdValue,
      highInterestThresholdValue,
      keep_warm_template,
    ]
  )

  return NextResponse.json({ preferences: rows[0] })
}
