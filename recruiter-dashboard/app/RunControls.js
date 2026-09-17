'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'

const POLL_MS = 3000

function StepIcon({ status, conclusion }) {
  if (status === 'completed') {
    if (conclusion === 'success') return <span className="step-icon step-icon-success">✓</span>
    if (conclusion === 'skipped' || conclusion === 'cancelled') {
      return <span className="step-icon step-icon-skipped">–</span>
    }
    return <span className="step-icon step-icon-failure">✕</span>
  }
  if (status === 'in_progress') return <span className="step-icon step-icon-active">●</span>
  return <span className="step-icon step-icon-pending">○</span>
}

// `initialRunId` comes from run_state.active_run_id (Postgres) - set by
// /api/run-now and cleared once /api/run-status observes completion. That
// round trip is what lets this component pick up a still-running run on a
// fresh page load instead of forgetting about work that's actually still
// happening on GitHub's servers.
export default function RunControls({ initialRunId }) {
  // idle | starting | running | done | error
  const [phase, setPhase] = useState(initialRunId ? 'running' : 'idle')
  const [runId, setRunId] = useState(initialRunId || null)
  const [steps, setSteps] = useState([])
  const [conclusion, setConclusion] = useState(null)
  const [htmlUrl, setHtmlUrl] = useState(null)
  const [message, setMessage] = useState(null)
  const pollRef = useRef(null)
  const router = useRouter()

  function stopPolling() {
    clearInterval(pollRef.current)
    pollRef.current = null
  }

  function pollStatus(id) {
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/run-status/${id}`)
        if (!res.ok) return
        const data = await res.json()
        setSteps(data.steps || [])
        setHtmlUrl(data.htmlUrl || null)
        if (data.status === 'completed') {
          stopPolling()
          setConclusion(data.conclusion)
          setPhase('done')
          router.refresh()
        }
      } catch {
        // transient fetch error - just try again on the next tick
      }
    }, POLL_MS)
  }

  useEffect(() => {
    if (initialRunId) {
      pollStatus(initialRunId)
    }
    return () => clearInterval(pollRef.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleRunNow() {
    setPhase('starting')
    setMessage(null)
    setConclusion(null)
    setSteps([])
    try {
      const res = await fetch('/api/run-now', { method: 'POST' })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setPhase('error')
        setMessage(data.error || 'Failed to trigger the run.')
        return
      }
      if (data.runId) {
        setRunId(data.runId)
        setPhase('running')
        pollStatus(data.runId)
      } else {
        // Dispatched, but we couldn't locate the run to track live -
        // still a success, just without a live checklist.
        setPhase('error')
        setMessage('Triggered, but could not attach live status — check the Actions tab.')
      }
    } catch {
      setPhase('error')
      setMessage('Failed to trigger the run.')
    }
  }

  function reset() {
    setPhase('idle')
    setRunId(null)
    setSteps([])
    setConclusion(null)
    setMessage(null)
    fetch('/api/run-state', { method: 'DELETE' }).catch(() => {})
  }

  if (phase === 'idle' || phase === 'error') {
    return (
      <span className="run-controls">
        <button type="button" className="btn" onClick={handleRunNow}>
          Run now
        </button>
        {message && <span className="warning"> {message}</span>}
      </span>
    )
  }

  return (
    <div className="run-panel">
      <div className="run-panel-header">
        {phase !== 'done' && <span className="step-icon spinner" />}
        <span className="run-panel-title">
          {phase === 'starting' && 'Starting…'}
          {phase === 'running' && 'Running triage…'}
          {phase === 'done' &&
            (conclusion === 'success' ? 'Run complete' : `Run finished (${conclusion})`)}
        </span>
        {htmlUrl && (
          <a href={htmlUrl} target="_blank" rel="noreferrer" className="muted">
            view on GitHub
          </a>
        )}
      </div>

      {steps.length > 0 && (
        <ul className="run-steps">
          {steps.map((step, i) => (
            <li key={i}>
              <StepIcon status={step.status} conclusion={step.conclusion} />
              <span>{step.name}</span>
            </li>
          ))}
        </ul>
      )}

      {phase !== 'done' && (
        <div className="muted run-note">
          This keeps running on GitHub even if you close this tab — it's fine to come back
          later, new results will just be here waiting.
        </div>
      )}

      {phase === 'done' && (
        <button type="button" className="btn" onClick={reset}>
          Dismiss
        </button>
      )}
    </div>
  )
}
