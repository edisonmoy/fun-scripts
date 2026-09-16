'use client'

import { useState } from 'react'

export default function RunControls() {
  const [status, setStatus] = useState('idle') // idle | running | done | error

  async function handleRunNow() {
    setStatus('running')
    try {
      const res = await fetch('/api/run-now', { method: 'POST' })
      setStatus(res.ok ? 'done' : 'error')
    } catch {
      setStatus('error')
    }
  }

  return (
    <span className="run-controls">
      <button type="button" className="btn btn-primary" onClick={handleRunNow} disabled={status === 'running'}>
        {status === 'running' ? 'Starting…' : 'Run now'}
      </button>
      {status === 'done' && (
        <span className="muted">
          {' '}
          Triggered —{' '}
          <a
            href="https://github.com/edisonmoy/fun-scripts/actions/workflows/gmail-recruiter-triage.yml"
            target="_blank"
            rel="noreferrer"
          >
            watch it run
          </a>
          , then reload this page in a minute or two.
        </span>
      )}
      {status === 'error' && (
        <span className="warning"> Failed to trigger — check the Action manually.</span>
      )}
    </span>
  )
}
