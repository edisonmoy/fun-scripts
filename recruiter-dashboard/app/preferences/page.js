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
        Sync uses these to decide what counts as high-interest and how to draft replies.
        Nothing is sent until you click Send.
      </p>
      <PreferencesForm initial={preferences} />
    </div>
  )
}
