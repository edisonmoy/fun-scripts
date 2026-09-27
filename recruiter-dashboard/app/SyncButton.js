'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'

// Pulls new recruiter emails from Gmail, classifies them and drafts
// replies - never sends anything. Each /api/sync call handles one time-boxed
// batch, so this keeps calling until nothing is left, refreshing the list
// as rows land.
export default function SyncButton() {
  const [syncing, setSyncing] = useState(false)
  const [message, setMessage] = useState(null)
  const [isError, setIsError] = useState(false)
  const router = useRouter()

  async function handleSync() {
    setSyncing(true)
    setIsError(false)
    setMessage('Checking Gmail…')
    const failed = []
    let processed = 0

    try {
      for (;;) {
        const res = await fetch('/api/sync', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ skip: failed }),
        })
        const data = await res.json().catch(() => ({}))
        if (!res.ok) throw new Error(data.error || `Sync failed (${res.status})`)

        processed += data.processed
        failed.push(...data.failed)
        if (data.processed > 0) router.refresh()
        if (data.remaining === 0) break
        setMessage(`Synced ${processed} of ${processed + failed.length + data.remaining}…`)
      }

      if (failed.length > 0) {
        setIsError(true)
        setMessage(
          `Synced ${processed}. ${failed.length} failed - they'll be retried next sync.`
        )
      } else {
        setMessage(processed === 0 ? 'Up to date.' : `Synced ${processed} new.`)
      }
    } catch (err) {
      setIsError(true)
      setMessage(err.message)
    } finally {
      setSyncing(false)
      router.refresh()
    }
  }

  return (
    <span className="run-controls">
      <button type="button" className="btn" onClick={handleSync} disabled={syncing}>
        {syncing && <span className="step-icon spinner" />}
        {syncing ? 'Syncing…' : 'Sync'}
      </button>
      {message && <span className={isError ? 'warning' : 'muted'}> {message}</span>}
    </span>
  )
}
