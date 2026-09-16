import Link from 'next/link'
import { query } from '../../lib/db'
import LogoutButton from '../LogoutButton'
import PreferencesForm from './PreferencesForm'

export const dynamic = 'force-dynamic'

async function getPreferences() {
  const { rows } = await query('SELECT * FROM preferences WHERE id = 1')
  return rows[0] || {}
}

export default async function PreferencesPage() {
  const preferences = await getPreferences()

  return (
    <div className="container">
      <div className="header">
        <h1>Triage Preferences</h1>
        <nav>
          <Link href="/">Back to triage list</Link>
          <LogoutButton />
        </nav>
      </div>
      <p className="muted">
        These preferences are read by the daily triage job to decide what counts as
        high-interest, how to draft replies, and whether to send automatically.
      </p>
      <PreferencesForm initial={preferences} />
    </div>
  )
}
