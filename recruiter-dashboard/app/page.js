import Link from 'next/link'
import { query } from '../lib/db'
import LogoutButton from './LogoutButton'
import RecordRow from './RecordRow'
import RunControls from './RunControls'

export const dynamic = 'force-dynamic'

function fmtDate(value) {
  if (!value) return null
  return new Date(value).toLocaleString()
}

async function getRunState() {
  const { rows } = await query('SELECT last_run_at FROM run_state WHERE id = 1')
  return rows[0] || null
}

async function getRecords({ category, showIgnored }) {
  const conditions = []
  const params = []

  if (category) {
    params.push(category)
    conditions.push(`category = $${params.length}`)
  }
  if (!showIgnored) {
    conditions.push(`status <> 'ignored'`)
  }

  const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''
  const { rows } = await query(
    `SELECT * FROM triage_records ${where} ORDER BY created_at DESC`,
    params
  )
  return rows
}

function tabHref(category, showIgnored) {
  const params = new URLSearchParams()
  if (category) params.set('category', category)
  if (showIgnored) params.set('showIgnored', '1')
  const qs = params.toString()
  return qs ? `/?${qs}` : '/'
}

export default async function DashboardPage({ searchParams }) {
  const sp = (await searchParams) || {}
  const category = ['ignore', 'keep_warm', 'high_interest'].includes(sp.category)
    ? sp.category
    : null
  const showIgnored = sp.showIgnored === '1'

  const [runState, records] = await Promise.all([
    getRunState(),
    getRecords({ category, showIgnored }),
  ])

  return (
    <div className="container">
      <div className="header">
        <h1>Recruiter Triage</h1>
        <div>
          <span className="muted">
            Last automation run:{' '}
            {runState?.last_run_at ? fmtDate(runState.last_run_at) : 'never'}
          </span>
          <nav>
            <Link href="/preferences">Preferences</Link>
            <LogoutButton />
          </nav>
        </div>
      </div>

      <div className="run-section">
        <RunControls />
      </div>

      <div className="tabs-row">
        <div className="tabs">
          <Link className={`${!category ? 'active' : ''}`} href={tabHref(null, showIgnored)}>
            All
          </Link>
          <Link
            className={`${category === 'keep_warm' ? 'active' : ''}`}
            href={tabHref('keep_warm', showIgnored)}
          >
            Keep Warm
          </Link>
          <Link
            className={`${category === 'high_interest' ? 'active' : ''}`}
            href={tabHref('high_interest', showIgnored)}
          >
            High Interest
          </Link>
          <Link
            className={`${category === 'ignore' ? 'active' : ''}`}
            href={tabHref('ignore', showIgnored)}
          >
            Ignore (category)
          </Link>
        </div>
        <Link className="toggle-link" href={tabHref(category, !showIgnored)}>
          {showIgnored ? 'Hide ignored status' : 'Show ignored status'}
        </Link>
      </div>

      {records.length === 0 && <div className="empty">No records match this filter.</div>}

      <div className="row-list">
        {records.map((record) => (
          <RecordRow
            key={record.id}
            id={record.id}
            subject={record.subject}
            sender={record.sender}
            dateDisplay={fmtDate(record.received_at) || fmtDate(record.created_at)}
            category={record.category}
            status={record.status}
            extracted={record.extracted_json}
            summary={record.extracted_json?.summary}
            rationale={record.rationale}
            draftSubject={record.draft_subject}
            draftBody={record.draft_body}
            gmailDraftId={record.gmail_draft_id}
          />
        ))}
      </div>
    </div>
  )
}
