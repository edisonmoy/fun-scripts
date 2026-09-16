import { NextResponse } from 'next/server'
import { query } from '../../../lib/db'

const CATEGORIES = new Set(['ignore', 'keep_warm', 'high_interest'])
const STATUSES = new Set(['drafted', 'approved_pending', 'sent', 'ignored', 'rejected'])

export async function GET(request) {
  const { searchParams } = new URL(request.url)
  const category = searchParams.get('category')
  const status = searchParams.get('status')

  if (category && !CATEGORIES.has(category)) {
    return NextResponse.json({ error: `invalid category: ${category}` }, { status: 400 })
  }
  if (status && !STATUSES.has(status)) {
    return NextResponse.json({ error: `invalid status: ${status}` }, { status: 400 })
  }

  const conditions = []
  const params = []
  if (category) {
    params.push(category)
    conditions.push(`category = $${params.length}`)
  }
  if (status) {
    params.push(status)
    conditions.push(`status = $${params.length}`)
  }

  const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''
  const { rows } = await query(
    `SELECT * FROM triage_records ${where} ORDER BY created_at DESC`,
    params
  )
  return NextResponse.json({ records: rows })
}
