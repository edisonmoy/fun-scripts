'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'

const CATEGORY_LABELS = {
  ignore: 'Ignore',
  keep_warm: 'Keep Warm',
  high_interest: 'High Interest',
}

const STATUS_LABELS = {
  drafted: 'Drafted',
  approved_pending: 'Approved · pending send',
  sent: 'Sent',
  ignored: 'Ignored',
  rejected: 'Rejected',
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

  if (fields.length === 0) return null

  return (
    <dl className="extracted">
      {fields.map(([label, value]) => (
        <div className="extracted-row" key={label}>
          <dt>{label}</dt>
          <dd>{String(value)}</dd>
        </div>
      ))}
    </dl>
  )
}

export default function RecordRow({
  id,
  subject,
  sender,
  dateDisplay,
  category,
  status,
  extracted,
  summary,
  rationale,
  draftSubject,
  draftBody,
  gmailDraftId,
}) {
  const [expanded, setExpanded] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)
  const router = useRouter()

  async function setStatus(next, e) {
    e.stopPropagation()
    setPending(true)
    setError(null)
    try {
      const res = await fetch(`/api/triage/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: next }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.error || `request failed (${res.status})`)
      }
      router.refresh()
    } catch (err) {
      setError(err.message)
      setPending(false)
    }
  }

  return (
    <div className={`row row-${category} ${expanded ? 'row-expanded' : ''}`}>
      <button
        type="button"
        className="row-summary"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <span className="row-main">
          <span className="row-subject">{subject || '(no subject)'}</span>
          <span className="row-sender">{sender}</span>
        </span>
        <span className="row-meta">
          <span className="row-status">{STATUS_LABELS[status] || status}</span>
          <span className="row-date">{dateDisplay}</span>
        </span>
      </button>

      {expanded && (
        <div className="row-detail">
          <div className="row-detail-label">{CATEGORY_LABELS[category] || category}</div>

          <ExtractedFields extracted={extracted} />
          {summary && <div className="draft-text">{summary}</div>}

          {rationale && (
            <div className="why">
              <span className="why-label">Why</span> {rationale}
            </div>
          )}

          {draftBody && (
            <div className="draft">
              <div className="draft-subject">{draftSubject}</div>
              <div className="draft-body">{draftBody}</div>
              {gmailDraftId && (
                <div className="muted">
                  Also saved as a Gmail draft &mdash; edit it there directly if you want to
                  change the wording before it sends.
                </div>
              )}
            </div>
          )}

          {status === 'drafted' && (
            <div>
              <div className="actions">
                <button
                  className="btn btn-success"
                  disabled={pending}
                  onClick={(e) => setStatus('approved_pending', e)}
                >
                  Approve
                </button>
                <button
                  className="btn btn-danger"
                  disabled={pending}
                  onClick={(e) => setStatus('rejected', e)}
                >
                  Reject
                </button>
              </div>
              {error && <div className="warning">{error}</div>}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
