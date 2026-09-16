import Link from 'next/link'
import { query } from '../lib/db'
import LogoutButton from './LogoutButton'
import RunControls from './RunControls'
import TriageActions from './TriageActions'

export const dynamic = 'force-dynamic'

const CATEGORY_LABELS = {
  ignore: 'Ignore',
  keep_warm: 'Keep Warm',
  high_interest: 'High Interest',
}

const STATUS_LABELS = {
  drafted: 'Drafted',
  approved_pending: 'Approved (pending send)',
  sent: 'Sent',
  ignored: 'Ignored',
  rejected: 'Rejected',
}

function badge(kind, value, label) {
  return <span className={`badge badge-${kind}-${value}`}>{label}</span>
}

function fmtDate(value) {
  if (!value) return null
  return new Date(value).toLocaleString()
}

function ExtractedFields({ extracted }) {
  const data = extracted || {}
  const fields = [
    ['Company', data.company],
    ['Role', data.role],
    ['Seniority', data.seniority],
    ['Comp', data.comp],
    ['Location', data.location_or_remote],
  ].filter(([, v]) => v !== undefined && v !== null && v !== '')

  return (
    <div className="extracted">
      {fields.length > 0 && (
        <dl>
          {fields.map(([label, value]) => (
            <>
              <dt key={`${label}-dt`}>{label}</dt>
              <dd key={`${label}-dd`}>{String(value)}</dd>
            </>
          ))}
        </dl>
      )}
      {data.summary && <div className="draft-text">{data.summary}</div>}
    </div>
  )
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
            <RunControls />
            <Link href="/preferences">Preferences</Link>
            <LogoutButton />
          </nav>
        </div>
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

      {records.map((record) => (
        <div className="record" key={record.id}>
          <div className="record-top">
            <div>
              <div className="subject">{record.subject || '(no subject)'}</div>
              <div className="muted">
                {record.sender} &middot; {fmtDate(record.received_at) || fmtDate(record.created_at)}
              </div>
            </div>
            <div>
              {badge('category', record.category, CATEGORY_LABELS[record.category] || record.category)}
              {badge('status', record.status, STATUS_LABELS[record.status] || record.status)}
            </div>
          </div>

          <ExtractedFields extracted={record.extracted_json} />

          {record.rationale && (
            <details className="why">
              <summary>Why?</summary>
              <div>{record.rationale}</div>
            </details>
          )}

          {record.draft_body && (
            <div className="draft">
              <div className="draft-subject">{record.draft_subject}</div>
              <div className="draft-body">{record.draft_body}</div>
              {record.gmail_draft_id && (
                <div className="muted">
                  Also saved as a Gmail draft (id: {record.gmail_draft_id}) &mdash; edit it there
                  directly if you want to change the wording before it sends.
                </div>
              )}
            </div>
          )}

          {record.status === 'drafted' && <TriageActions id={record.id} />}
        </div>
      ))}
    </div>
  )
}
