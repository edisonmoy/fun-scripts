'use client'

import { useState } from 'react'

const DEFAULT_KEEP_WARM_HINT =
  "Leave blank to use the default: thanks, one specific comment, then 'Happy to reconnect if things change in the future.'"
const DEFAULT_HIGH_INTEREST_HINT =
  'Leave blank to let the model draft a substantive reply with a clarifying question.'

export default function PreferencesForm({ initial }) {
  const [form, setForm] = useState({
    target_areas: initial.target_areas || '',
    seniority: initial.seniority || '',
    comp_floor: initial.comp_floor ?? '',
    company_excludes: initial.company_excludes || '',
    keep_warm_template: initial.keep_warm_template || '',
    high_interest_template: initial.high_interest_template || '',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [savedAt, setSavedAt] = useState(null)
  const [templateTab, setTemplateTab] = useState('keep_warm')

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

      <label htmlFor="comp_floor">Comp floor</label>
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

      <label>Reply templates</label>
      <div className="subtabs">
        <button
          type="button"
          className={templateTab === 'keep_warm' ? 'active' : ''}
          onClick={() => setTemplateTab('keep_warm')}
        >
          Keep Warm
        </button>
        <button
          type="button"
          className={templateTab === 'high_interest' ? 'active' : ''}
          onClick={() => setTemplateTab('high_interest')}
        >
          High Interest
        </button>
      </div>

      {templateTab === 'keep_warm' && (
        <div className="template-panel">
          <textarea
            id="keep_warm_template"
            aria-label="Keep Warm reply template"
            className="template-input"
            value={form.keep_warm_template}
            onChange={(e) => update('keep_warm_template', e.target.value)}
            placeholder={DEFAULT_KEEP_WARM_HINT}
          />
        </div>
      )}

      {templateTab === 'high_interest' && (
        <div className="template-panel">
          <textarea
            id="high_interest_template"
            aria-label="High Interest reply template"
            className="template-input"
            value={form.high_interest_template}
            onChange={(e) => update('high_interest_template', e.target.value)}
            placeholder={DEFAULT_HIGH_INTEREST_HINT}
          />
        </div>
      )}

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
