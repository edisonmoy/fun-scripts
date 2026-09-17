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
  const { rows } = await query('SELECT last_run_at, active_run_id FROM run_state WHERE id = 1')
  return rows[0] || null
}

const SORT_OPTIONS = {
  newest: 'created_at DESC',
  oldest: 'created_at ASC',
  fit_desc: 'fit_score DESC NULLS LAST, created_at DESC',
  fit_asc: 'fit_score ASC NULLS LAST, created_at DESC',
}

// Cross-category status views - status='sent'/'approved_pending' rows are
// excluded from the default category tabs (below) and only live here,
// same treatment 'ignored' already got via the showIgnored toggle.
const STATUS_VIEWS = {
  pending: 'approved_pending',
  sent: 'sent',
}

async function getRecords({ category, showIgnored, view, sort }) {
  const orderBy = SORT_OPTIONS[sort] || SORT_OPTIONS.newest

  if (STATUS_VIEWS[view]) {
    const { rows } = await query(
      `SELECT * FROM triage_records WHERE status = $1 ORDER BY ${orderBy}`,
      [STATUS_VIEWS[view]]
    )
    return rows
  }

  const conditions = ["status <> 'sent'"]
  const params = []

  if (category) {
    params.push(category)
    conditions.push(`category = $${params.length}`)
  }
  if (!showIgnored) {
    conditions.push(`status <> 'ignored'`)
  }

  const { rows } = await query(
    `SELECT * FROM triage_records WHERE ${conditions.join(' AND ')} ORDER BY ${orderBy}`,
    params
  )
  return rows
}

// Single source of truth for building nav links so every control (category
// tabs, status views, ignored toggle, sort) can change one dimension of the
// URL while preserving the others.
function buildHref(current, overrides) {
  const merged = { ...current, ...overrides }
  const params = new URLSearchParams()
  if (merged.view) params.set('view', merged.view)
  if (!merged.view && merged.category) params.set('category', merged.category)
  if (merged.showIgnored) params.set('showIgnored', '1')
  if (merged.sort && merged.sort !== 'newest') params.set('sort', merged.sort)
  const qs = params.toString()
  return qs ? `/?${qs}` : '/'
}

export default async function DashboardPage({ searchParams }) {
  const sp = (await searchParams) || {}
  const view = STATUS_VIEWS[sp.view] ? sp.view : null
  const category = ['ignore', 'keep_warm', 'high_interest'].includes(sp.category)
    ? sp.category
    : null
  const showIgnored = sp.showIgnored === '1'
  const sort = SORT_OPTIONS[sp.sort] ? sp.sort : 'newest'
  const current = { category, showIgnored, view, sort }

  const [runState, records] = await Promise.all([
    getRunState(),
    getRecords({ category, showIgnored, view, sort }),
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
        <RunControls initialRunId={runState?.active_run_id || null} />
      </div>

      <div className="tabs-row">
        <div className="tabs">
          <Link
            className={!view && !category && !showIgnored ? 'active' : ''}
            href={buildHref(current, { category: null, view: null, showIgnored: false })}
          >
            All
          </Link>
          <Link
            className={!view && category === 'keep_warm' ? 'active' : ''}
            href={buildHref(current, { category: 'keep_warm', view: null, showIgnored: false })}
          >
            Keep Warm
          </Link>
          <Link
            className={!view && category === 'high_interest' ? 'active' : ''}
            href={buildHref(current, {
              category: 'high_interest',
              view: null,
              showIgnored: false,
            })}
          >
            High Interest
          </Link>
          <Link
            className={view === 'pending' ? 'active' : ''}
            href={buildHref(current, { view: 'pending', category: null, showIgnored: false })}
          >
            Pending Send
          </Link>
          <Link
            className={view === 'sent' ? 'active' : ''}
            href={buildHref(current, { view: 'sent', category: null, showIgnored: false })}
          >
            Sent
          </Link>
          <Link
            className={!view && showIgnored ? 'active' : ''}
            href={buildHref(current, { showIgnored: true, category: null, view: null })}
          >
            Ignored
          </Link>
        </div>
      </div>

      <div className="sort-row">
        <span className="muted">Sort:</span>
        <Link
          className={sort === 'newest' ? 'active' : ''}
          href={buildHref(current, { sort: 'newest' })}
        >
          Newest
        </Link>
        <Link
          className={sort === 'oldest' ? 'active' : ''}
          href={buildHref(current, { sort: 'oldest' })}
        >
          Oldest
        </Link>
        <Link
          className={sort === 'fit_desc' ? 'active' : ''}
          href={buildHref(current, { sort: 'fit_desc' })}
        >
          Best fit
        </Link>
        <Link
          className={sort === 'fit_asc' ? 'active' : ''}
          href={buildHref(current, { sort: 'fit_asc' })}
        >
          Worst fit
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
            fitScore={record.fit_score}
            extracted={record.extracted_json}
            summary={record.extracted_json?.summary}
            rationale={record.rationale}
            draftSubject={record.draft_subject}
            draftBody={record.draft_body}
          />
        ))}
      </div>
    </div>
  )
}
