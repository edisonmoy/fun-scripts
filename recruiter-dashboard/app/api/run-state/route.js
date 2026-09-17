import { NextResponse } from 'next/server'
import { query } from '../../../lib/db'

// Called when the user dismisses a completed run panel, so a page reload
// can't resurrect it. The run-status poll already clears active_run_id the
// moment it observes completion, but Dismiss only ever appears after that
// has happened - this is a belt-and-suspenders clear for any case where the
// row was left stuck (a dropped poll, a stale tab, etc).
export async function DELETE() {
  await query('UPDATE run_state SET active_run_id = NULL WHERE id = 1')
  return NextResponse.json({ ok: true })
}
