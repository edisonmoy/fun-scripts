"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { Target } from "@/lib/github";

function emptyTarget(): Target {
  return {
    key: "",
    venue_name: "",
    request: "",
    venue_id: null,
    party_size_override: null,
    enabled: true,
    dry_run: null,
  };
}

export default function DashboardPage() {
  const [targets, setTargets] = useState<Target[] | null>(null);
  const [sha, setSha] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<{ text: string; kind: "success" | "error" } | null>(
    null
  );
  const router = useRouter();

  async function load() {
    setLoadError(null);
    const res = await fetch("/api/targets");
    const data = await res.json();
    if (!res.ok) {
      setLoadError(data.error || "Failed to load targets");
      return;
    }
    setTargets(data.targets);
    setSha(data.sha);
  }

  useEffect(() => {
    load();
  }, []);

  function updateTarget(index: number, patch: Partial<Target>) {
    if (!targets) return;
    const next = [...targets];
    next[index] = { ...next[index], ...patch };
    setTargets(next);
  }

  function removeTarget(index: number) {
    if (!targets) return;
    if (!confirm(`Remove target "${targets[index].key || "(unnamed)"}"?`)) return;
    setTargets(targets.filter((_, i) => i !== index));
  }

  function addTarget() {
    setTargets([...(targets || []), emptyTarget()]);
  }

  async function save() {
    if (!targets || sha === null) return;
    setSaving(true);
    setSaveMessage(null);
    const res = await fetch("/api/targets", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        targets,
        sha,
        message: "Update resy-sniper targets via web UI",
      }),
    });
    const data = await res.json();
    setSaving(false);
    if (!res.ok) {
      setSaveMessage({ text: data.error || "Save failed", kind: "error" });
      return;
    }
    setSaveMessage({
      text: "Saved. The bot redeploys automatically in ~1-2 min to pick this up.",
      kind: "success",
    });
    await load(); // refresh sha for the next save
  }

  async function logout() {
    await fetch("/api/logout", { method: "POST" });
    router.push("/login");
    router.refresh();
  }

  if (loadError) {
    return (
      <main>
        <h1>Resy sniper targets</h1>
        <div className="status-message error">{loadError}</div>
      </main>
    );
  }

  if (!targets) {
    return (
      <main>
        <h1>Resy sniper targets</h1>
        <p className="subtitle">Loading...</p>
      </main>
    );
  }

  return (
    <main>
      <div className="target-header">
        <div>
          <h1>Resy sniper targets</h1>
          <p className="subtitle">
            Reservations the bot is watching. Saving commits to GitHub, which redeploys the bot.
          </p>
        </div>
        <button onClick={logout}>Log out</button>
      </div>

      {targets.length === 0 && (
        <div className="empty-state">No targets yet - add one below.</div>
      )}

      {targets.map((t, i) => (
        <div className="card" key={i}>
          <div className="target-header">
            <input
              className="target-key-input"
              placeholder="unique-key (e.g. pizza4ps-brooklyn-saturday)"
              value={t.key}
              onChange={(e) => updateTarget(i, { key: e.target.value })}
            />
            <div className="row-controls">
              <label className="toggle-label">
                <input
                  type="checkbox"
                  checked={t.enabled !== false}
                  onChange={(e) => updateTarget(i, { enabled: e.target.checked })}
                />
                Enabled
              </label>
              <button className="danger" onClick={() => removeTarget(i)}>
                Remove
              </button>
            </div>
          </div>

          <div className="field-row">
            <label>Venue name</label>
            <input
              type="text"
              placeholder="e.g. Pizza 4P's Brooklyn"
              value={t.venue_name}
              onChange={(e) => updateTarget(i, { venue_name: e.target.value })}
            />
          </div>

          <div className="field-row">
            <label>Venue ID</label>
            <input
              type="number"
              placeholder="optional - leave blank to auto-resolve from the name"
              value={t.venue_id ?? ""}
              onChange={(e) =>
                updateTarget(i, { venue_id: e.target.value ? Number(e.target.value) : null })
              }
            />
          </div>

          <div className="field-row">
            <label>Request</label>
            <div>
              <textarea
                placeholder='e.g. "A Saturday dinner reservation for 2, flexible on time between 5pm and 9pm. No date flexibility beyond Saturdays. Look up to 8 weeks out."'
                value={t.request}
                onChange={(e) => updateTarget(i, { request: e.target.value })}
              />
              <div className="notes-hint">
                Plain English - date/time flexibility, party size, etc. Parsed by Claude into search
                criteria when the bot starts.
              </div>
            </div>
          </div>

          <div className="field-row">
            <label>Party size override</label>
            <input
              type="number"
              placeholder="optional - overrides whatever the parser extracts"
              value={t.party_size_override ?? ""}
              onChange={(e) =>
                updateTarget(i, {
                  party_size_override: e.target.value ? Number(e.target.value) : null,
                })
              }
            />
          </div>

          <div className="field-row">
            <label>Dry run</label>
            <select
              value={t.dry_run === null || t.dry_run === undefined ? "default" : String(t.dry_run)}
              onChange={(e) =>
                updateTarget(i, {
                  dry_run: e.target.value === "default" ? null : e.target.value === "true",
                })
              }
            >
              <option value="default">Use global default</option>
              <option value="true">Dry run (log only, never books)</option>
              <option value="false">Live (will actually book)</option>
            </select>
          </div>
        </div>
      ))}

      <div className="toolbar">
        <button onClick={addTarget}>+ Add target</button>
        <div className="toolbar-actions">
          <button className="primary" onClick={save} disabled={saving}>
            {saving ? "Saving..." : "Save changes"}
          </button>
        </div>
      </div>

      {saveMessage && <div className={`status-message ${saveMessage.kind}`}>{saveMessage.text}</div>}
    </main>
  );
}
