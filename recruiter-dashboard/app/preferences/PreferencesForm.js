'use client'

import { useState } from 'react'

export default function PreferencesForm({ initial }) {
  const [form, setForm] = useState({
    target_areas: initial.target_areas || '',
    seniority: initial.seniority || '',
    comp_floor: initial.comp_floor ?? '',
    company_excludes: initial.company_excludes || '',
    autonomy_keep_warm: initial.autonomy_keep_warm || 'draft_only',
    autonomy_high_interest: initial.autonomy_high_interest || 'draft_only',
    tone_notes: initial.tone_notes || '',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [savedAt, setSavedAt] = useState(null)

  function update(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  async function onSubmit(e) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    setSavedAt(null)
    try {
      const res = await fetch('/api/preferences', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...form,
          comp_floor: form.comp_floor === '' ? null : Number(form.comp_floor),
        }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.error || `request failed (${res.status})`)
      }
      setSavedAt(new Date())
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="prefs" onSubmit={onSubmit}>
      <label htmlFor="target_areas">Target areas</label>
      <textarea
        id="target_areas"
        value={form.target_areas}
        onChange={(e) => update('target_areas', e.target.value)}
        placeholder="e.g. healthcare AI / patient outcomes, climate tech, venture studios"
      />

      <label htmlFor="seniority">Seniority</label>
      <input
        id="seniority"
        type="text"
        value={form.seniority}
        onChange={(e) => update('seniority', e.target.value)}
      />

      <label htmlFor="comp_floor">Comp floor (optional)</label>
      <input
        id="comp_floor"
        type="number"
        value={form.comp_floor}
        onChange={(e) => update('comp_floor', e.target.value)}
      />

      <label htmlFor="company_excludes">Company excludes</label>
      <textarea
        id="company_excludes"
        value={form.company_excludes}
        onChange={(e) => update('company_excludes', e.target.value)}
        placeholder="Companies you never want to hear from, one per line"
      />

      <label htmlFor="autonomy_keep_warm">Autonomy: keep-warm replies</label>
      <select
        id="autonomy_keep_warm"
        value={form.autonomy_keep_warm}
        onChange={(e) => update('autonomy_keep_warm', e.target.value)}
      >
        <option value="draft_only">Draft only (review before sending)</option>
        <option value="auto_send">Auto-send</option>
      </select>
      {form.autonomy_keep_warm === 'auto_send' && (
        <div className="warning">Warning: auto_send sends these replies without your review.</div>
      )}

      <label htmlFor="autonomy_high_interest">Autonomy: high-interest replies</label>
      <select
        id="autonomy_high_interest"
        value={form.autonomy_high_interest}
        onChange={(e) => update('autonomy_high_interest', e.target.value)}
      >
        <option value="draft_only">Draft only (review before sending)</option>
        <option value="auto_send">Auto-send</option>
      </select>
      {form.autonomy_high_interest === 'auto_send' && (
        <div className="warning">Warning: auto_send sends these replies without your review.</div>
      )}

      <label htmlFor="tone_notes">Tone notes</label>
      <textarea
        id="tone_notes"
        value={form.tone_notes}
        onChange={(e) => update('tone_notes', e.target.value)}
        placeholder="Notes for the model on how drafts should sound"
      />

      <div className="save-row">
        <button type="submit" className="btn btn-primary" disabled={saving}>
          {saving ? 'Saving...' : 'Save preferences'}
        </button>
        {savedAt && <span className="muted">Saved at {savedAt.toLocaleTimeString()}</span>}
        {error && <span className="warning">{error}</span>}
      </div>
    </form>
  )
}
