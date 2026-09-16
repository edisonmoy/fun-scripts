'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'

export default function TriageActions({ id }) {
  const router = useRouter()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)

  async function setStatus(status) {
    setPending(true)
    setError(null)
    try {
      const res = await fetch(`/api/triage/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
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
    <div>
      <div className="actions">
        <button
          className="btn btn-success"
          disabled={pending}
          onClick={() => setStatus('approved_pending')}
        >
          Approve
        </button>
        <button className="btn btn-danger" disabled={pending} onClick={() => setStatus('rejected')}>
          Reject
        </button>
      </div>
      {error && <div className="warning">{error}</div>}
    </div>
  )
}
