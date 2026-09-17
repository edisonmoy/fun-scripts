"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { Target } from "@/lib/github";

interface ValidationResult {
  venue?: { id: number; name: string; neighborhood: string | null; city: string | null };
  venue_error?: string;
  criteria?: {
    party_size: number;
    days_of_week: string[];
    time_window_start: string;
    time_window_end: string;
    lookahead_weeks: number;
    notes: string;
  };
  criteria_error?: string;
}

interface LiveReservation {
  reservation_id: number;
  cancellation: { allowed: boolean; fee?: { amount: number; applies: boolean; display?: { amount: string } } };
  cancellation_policy: string[];
}

function emptyTarget(): Target {
  return {
    key: "",
    venue_name: "",
    request: "",
    venue_id: null,
    enabled: true,
    dry_run: true, // new targets default to test mode until validated
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
        Booked · {formatReservation(target.booking.day, target.booking.time)} · party of{" "}
        {target.booking.party_size}
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
  const [savingIndex, setSavingIndex] = useState<number | null>(null);
  const [saveMessages, setSaveMessages] = useState<
    Record<number, { text: string; kind: "success" | "error" } | undefined>
  >({});
  const [validating, setValidating] = useState<Record<number, boolean>>({});
  const [validationResults, setValidationResults] = useState<Record<number, ValidationResult>>({});
  const [liveReservations, setLiveReservations] = useState<LiveReservation[] | null>(null);
  const [reservationsError, setReservationsError] = useState<string | null>(null);
  const [cancellingKey, setCancellingKey] = useState<string | null>(null);
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

  async function loadReservations() {
    setReservationsError(null);
    const res = await fetch("/api/reservations");
    const data = await res.json();
    if (!res.ok) {
      setReservationsError(data.error || "Failed to load live reservation status");
      return;
    }
    setLiveReservations(data.reservations);
  }

  useEffect(() => {
    load();
    loadReservations();
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
    requestAnimationFrame(() => {
      document.getElementById("target-key-0")?.focus();
    });
  }

  async function validateTarget(index: number) {
    if (!targets) return;
    const t = targets[index];
    setValidating((v) => ({ ...v, [index]: true }));
    const res = await fetch("/api/validate-target", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ venue_name: t.venue_name, request: t.request }),
    });
    const data: ValidationResult = await res.json();
    setValidating((v) => ({ ...v, [index]: false }));
    setValidationResults((v) => ({ ...v, [index]: data }));
    if (data.venue) {
      updateTarget(index, { venue_id: data.venue.id });
    }
  }

  async function saveTarget(index: number) {
    if (!targets || sha === null) return;
    setSavingIndex(index);
    setSaveMessages((m) => ({ ...m, [index]: undefined }));
    const res = await fetch("/api/targets", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        targets,
        sha,
        message: `Update target "${targets[index].key || "(unnamed)"}" via web UI`,
      }),
    });
    const data = await res.json();
    setSavingIndex(null);
    if (!res.ok) {
      setSaveMessages((m) => ({ ...m, [index]: { text: data.error || "Save failed", kind: "error" } }));
      return;
    }
    setSaveMessages((m) => ({
      ...m,
      [index]: { text: "Saved - bot redeploys in ~1-2 min.", kind: "success" },
    }));
    await load();
  }

  async function cancelBooking(index: number) {
    if (!targets) return;
    const t = targets[index];
    if (!t.booking) return;
    if (
      !confirm(
        `Cancel your reservation at ${t.venue_name} on ${t.booking.day}? This cancels the real reservation on Resy and can't be undone.`
      )
    ) {
      return;
    }
    setCancellingKey(t.key);
    const res = await fetch("/api/cancel-reservation", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: t.key, reservation_id: t.booking.reservation_id }),
    });
    const data = await res.json();
    setCancellingKey(null);
    if (!res.ok) {
      alert(data.error || "Cancel failed");
      return;
    }
    if (data.warning) alert(data.warning);
    await load();
    await loadReservations();
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

  const watching = targets.map((t, i) => ({ t, i })).filter(({ t }) => !t.booking);
  const booked = targets.map((t, i) => ({ t, i })).filter(({ t }) => !!t.booking);

  return (
    <main>
      <div className="target-header">
        <div>
          <h1>Resy sniper targets</h1>
          <p className="subtitle">
            Reservations the bot is watching. Each card's Save button commits every change on the
            page to GitHub, which redeploys the bot.
          </p>
        </div>
        <button onClick={logout}>Log out</button>
      </div>

      <div className="action-toolbar">
        <button className="primary" onClick={addTarget}>
          + Add target
        </button>
      </div>

      {targets.length === 0 && <div className="empty-state">No targets yet - add one above.</div>}

      {watching.map(({ t, i }) => {
        const result = validationResults[i];
        return (
          <div className="card" key={i}>
            <div className="target-header">
              <input
                id={`target-key-${i}`}
                className="target-key-input"
                placeholder="short-unique-key"
                value={t.key}
                onChange={(e) => updateTarget(i, { key: e.target.value })}
              />
              <div className="row-controls">
                <StatusBadge target={t} />
              </div>
            </div>

            <div className="field-row">
              <label>Venue name</label>
              <div>
                <input
                  type="text"
                  placeholder="e.g. Pizza 4P's Brooklyn"
                  value={t.venue_name}
                  onChange={(e) => updateTarget(i, { venue_name: e.target.value })}
                />
                {t.venue_id != null && !result?.venue_error && (
                  <div className="notes-hint">Resolved to venue #{t.venue_id}</div>
                )}
              </div>
            </div>

            <div className="field-row">
              <label>Request</label>
              <div>
                <textarea
                  placeholder="Saturday dinner for 2, flexible 5-9pm, next 8 weeks"
                  value={t.request}
                  onChange={(e) => updateTarget(i, { request: e.target.value })}
                />
                <div className="notes-hint">
                  Plain English - party size, date/time flexibility, how far out to look. Parsed
                  by Claude into search criteria.
                </div>
              </div>
            </div>

            <div className="field-row">
              <label>Enabled</label>
              <label className="toggle-label">
                <input
                  type="checkbox"
                  checked={t.enabled !== false}
                  onChange={(e) => updateTarget(i, { enabled: e.target.checked })}
                />
                Actively watching (uncheck to pause without deleting)
              </label>
            </div>

            <div className="field-row">
              <label>Test mode</label>
              <label className="toggle-label">
                <input
                  type="checkbox"
                  checked={t.dry_run === true}
                  onChange={(e) => updateTarget(i, { dry_run: e.target.checked })}
                />
                Log matches only, don&apos;t actually book
              </label>
            </div>

            {result && (
              <div className="validation-panel">
                {result.venue && (
                  <div className="validation-line success">
                    ✓ Venue: {result.venue.name}
                    {result.venue.neighborhood ? `, ${result.venue.neighborhood}` : ""}
                    {result.venue.city ? `, ${result.venue.city}` : ""} (#{result.venue.id})
                  </div>
                )}
                {result.venue_error && (
                  <div className="validation-line error">✗ Venue not found: {result.venue_error}</div>
                )}
                {result.criteria && (
                  <div className="validation-line success">
                    ✓ Parsed: party of {result.criteria.party_size},{" "}
                    {result.criteria.days_of_week.join("/")}, {result.criteria.time_window_start}–
                    {result.criteria.time_window_end}, next {result.criteria.lookahead_weeks} weeks
                    {result.criteria.notes && (
                      <div className="notes-hint">Note: {result.criteria.notes}</div>
                    )}
                  </div>
                )}
                {result.criteria_error && (
                  <div className="validation-line error">✗ Couldn&apos;t parse request: {result.criteria_error}</div>
                )}
              </div>
            )}

            <div className="card-actions">
              <div className="card-actions-left">
                <button onClick={() => validateTarget(i)} disabled={validating[i]}>
                  {validating[i] ? "Checking..." : "Check venue & request"}
                </button>
                <button className="danger" onClick={() => removeTarget(i)}>
                  Remove
                </button>
              </div>
              <button className="primary" onClick={() => saveTarget(i)} disabled={savingIndex === i}>
                {savingIndex === i ? "Saving..." : "Save"}
              </button>
            </div>
            {saveMessages[i] && (
              <div className={`status-message ${saveMessages[i].kind}`}>{saveMessages[i].text}</div>
            )}
          </div>
        );
      })}

      {booked.length > 0 && (
        <>
          <h2 className="section-heading">Booked</h2>
          {booked.map(({ t, i }) => {
            const liveRes = liveReservations?.find((r) => r.reservation_id === t.booking!.reservation_id);
            return (
              <div className="card card-booked" key={i}>
                <div className="target-header">
                  <div className="booked-title">
                    <strong>{t.venue_name}</strong>
                    <span className="booked-key">{t.key}</span>
                  </div>
                  <StatusBadge target={t} />
                </div>

                <div className="booked-detail">Reservation ID: {t.booking!.reservation_id}</div>

                {liveRes ? (
                  <div className="cancellation-terms">
                    {liveRes.cancellation_policy?.[0]}
                    {liveRes.cancellation.fee?.applies && (
                      <div className="cancellation-fee-warning">
                        Cancelling now charges{" "}
                        {liveRes.cancellation.fee.display?.amount ?? `$${liveRes.cancellation.fee.amount}`}{" "}
                        per guest.
                      </div>
                    )}
                  </div>
                ) : reservationsError ? (
                  <div className="notes-hint">Couldn&apos;t load live cancellation terms: {reservationsError}</div>
                ) : (
                  <div className="notes-hint">Loading cancellation terms...</div>
                )}

                <div className="card-actions">
                  <div className="card-actions-left">
                    <button className="danger" onClick={() => removeTarget(i)}>
                      Remove from list
                    </button>
                  </div>
                  <button
                    className="danger"
                    onClick={() => cancelBooking(i)}
                    disabled={cancellingKey === t.key || !liveRes}
                  >
                    {cancellingKey === t.key ? "Cancelling..." : "Cancel reservation"}
                  </button>
                </div>
              </div>
            );
          })}
        </>
      )}
    </main>
  );
}
