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

function fitTier(score) {
  if (score >= 70) return 'high'
  if (score >= 40) return 'mid'
  return 'low'
}

function FitMeter({ score }) {
  if (score === null || score === undefined) return null
  const clamped = Math.max(0, Math.min(100, score))
  return (
    <span className="fit-meter" title={`Fit score: ${clamped}/100`}>
      <span className="fit-meter-track">
        <span
          className={`fit-meter-fill fit-meter-${fitTier(clamped)}`}
          style={{ width: `${clamped}%` }}
        />
      </span>
      <span className="fit-meter-label">{clamped}</span>
    </span>
  )
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
  fitScore,
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
  const [sendState, setSendState] = useState('idle') // idle | sending | queued
  const [leaving, setLeaving] = useState(false)
  const [removed, setRemoved] = useState(false)
  const router = useRouter()

  async function patch(body, e) {
    e?.stopPropagation()
    setPending(true)
    setError(null)
    try {
      const res = await fetch(`/api/triage/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const respBody = await res.json().catch(() => ({}))
        throw new Error(respBody.error || `request failed (${res.status})`)
      }
      router.refresh()
    } catch (err) {
      setError(err.message)
      setPending(false)
    }
  }

  async function handleSend(e) {
    e.stopPropagation()
    setSendState('sending')
    setError(null)
    try {
      const patchRes = await fetch(`/api/triage/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'approved_pending' }),
      })
      if (!patchRes.ok) {
        const respBody = await patchRes.json().catch(() => ({}))
        throw new Error(respBody.error || `request failed (${patchRes.status})`)
      }
      // Trigger the automation right away rather than waiting for the next
      // scheduled run - this is what makes "Send" actually send promptly.
      await fetch('/api/run-now', { method: 'POST' })
      setSendState('queued')
      setLeaving(true)
      // Fade out locally, then unmount and let a background refresh
      // reconcile the real (now approved_pending) state. `removed` persists
      // across that refresh since this is the same component instance, so
      // the row stays out of the list rather than reappearing.
      setTimeout(() => {
        setRemoved(true)
        router.refresh()
      }, 280)
    } catch (err) {
      setError(err.message)
      setSendState('idle')
    }
  }

  if (removed) return null

  const isQuickSend = category === 'keep_warm' && status === 'drafted'
  const isPendingSend = status === 'approved_pending'

  return (
    <div
      className={`row row-${category} ${expanded ? 'row-expanded' : ''} ${
        leaving ? 'row-removing' : ''
      }`}
    >
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
          {status !== 'drafted' && (
            <span className="row-status">{STATUS_LABELS[status] || status}</span>
          )}
          <span className="row-date">{dateDisplay}</span>
          <span className={`toggle-arrow ${expanded ? 'toggle-arrow-open' : ''}`}>▾</span>
        </span>
      </button>

      <div className="row-preview">
        <FitMeter score={fitScore} />
        {rationale && <span className="row-blurb">{rationale}</span>}
      </div>

      {isQuickSend && sendState !== 'queued' && (
        <div className="row-quick-actions">
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={sendState === 'sending'}
            onClick={handleSend}
          >
            {sendState === 'sending' ? 'Sending…' : 'Send'}
          </button>
          <button
            type="button"
            className="toggle-link"
            aria-expanded={expanded}
            onClick={(e) => {
              e.stopPropagation()
              setExpanded((v) => !v)
            }}
          >
            More
            <span className={`toggle-arrow ${expanded ? 'toggle-arrow-open' : ''}`}>▾</span>
          </button>
          {error && <span className="warning"> {error}</span>}
        </div>
      )}

      {isQuickSend && sendState === 'queued' && (
        <div className="row-quick-actions">
          <span className="muted">
            Queued to send, safe to leave this open or come back later.
          </span>
        </div>
      )}

      {isPendingSend && (
        <div className="row-quick-actions">
          <button
            type="button"
            className="btn btn-danger btn-sm"
            disabled={pending}
            onClick={(e) => patch({ status: 'drafted' }, e)}
          >
            Cancel send
          </button>
          {error && <span className="warning"> {error}</span>}
        </div>
      )}

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
                  onClick={(e) => patch({ status: 'approved_pending' }, e)}
                >
                  Approve
                </button>
                <button
                  className="btn btn-danger"
                  disabled={pending}
                  onClick={(e) => patch({ status: 'rejected' }, e)}
                >
                  Reject
                </button>
                {category === 'keep_warm' && (
                  <button
                    className="btn"
                    disabled={pending}
                    onClick={(e) => patch({ category: 'high_interest' }, e)}
                  >
                    Mark as high interest
                  </button>
                )}
              </div>
              {error && <div className="warning">{error}</div>}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
