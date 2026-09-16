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

function formatReservation(day: string, time: string): string {
  const date = new Date(`${day}T00:00:00Z`);
  const dateStr = date.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
  const [hStr, mStr] = time.split(":");
  let h = parseInt(hStr, 10);
  const ampm = h >= 12 ? "PM" : "AM";
  h = h % 12 || 12;
  return `${dateStr} · ${h}:${mStr} ${ampm}`;
}

function StatusBadge({ target }: { target: Target }) {
  if (target.booking) {
    return (
      <span className="badge badge-booked">
        Booked · {formatReservation(target.booking.day, target.booking.time)}
      </span>
    );
  }
  if (target.enabled === false) {
    return <span className="badge badge-paused">Paused</span>;
  }
  return <span className="badge badge-watching">Watching</span>;
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
    setTargets([emptyTarget(), ...(targets || [])]);
    // Scroll the new (first) card into view and focus its key field.
    requestAnimationFrame(() => {
      document.getElementById("target-key-0")?.focus();
    });
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

  const watching = targets
    .map((t, i) => ({ t, i }))
    .filter(({ t }) => !t.booking);
  const booked = targets
    .map((t, i) => ({ t, i }))
    .filter(({ t }) => !!t.booking);

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

      <div className="action-toolbar">
        <button className="primary" onClick={addTarget}>
          + Add target
        </button>
        <button className="primary" onClick={save} disabled={saving}>
          {saving ? "Saving..." : "Save changes"}
        </button>
      </div>
      {saveMessage && <div className={`status-message ${saveMessage.kind}`}>{saveMessage.text}</div>}

      {targets.length === 0 && (
        <div className="empty-state">No targets yet - add one above.</div>
      )}

      {watching.map(({ t, i }) => (
        <div className="card" key={i}>
          <div className="target-header">
            <input
              id={`target-key-${i}`}
              className="target-key-input"
              placeholder="unique-key (e.g. pizza4ps-brooklyn-saturday)"
              value={t.key}
              onChange={(e) => updateTarget(i, { key: e.target.value })}
            />
            <div className="row-controls">
              <StatusBadge target={t} />
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

      {booked.length > 0 && (
        <>
          <h2 className="section-heading">Booked</h2>
          {booked.map(({ t, i }) => (
            <div className="card card-booked" key={i}>
              <div className="target-header">
                <div className="booked-title">
                  <strong>{t.venue_name}</strong>
                  <span className="booked-key">{t.key}</span>
                </div>
                <div className="row-controls">
                  <StatusBadge target={t} />
                  <button className="danger" onClick={() => removeTarget(i)}>
                    Remove
                  </button>
                </div>
              </div>
              <div className="booked-detail">
                Reservation ID: <code>{t.booking!.reservation_id}</code>
              </div>
            </div>
          ))}
        </>
      )}
    </main>
  );
}
