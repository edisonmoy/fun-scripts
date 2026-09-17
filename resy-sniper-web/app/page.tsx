"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { Target } from "@/lib/github";

interface ValidationResult {
  venue?: { id: number; name: string; neighborhood: string | null; address: string | null };
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
  cancellation_preview?: string[] | null;
  cancellation_preview_note?: string;
}

interface LiveReservation {
  reservation_id: number;
  cancellation: { allowed: boolean; fee?: { amount: number; applies: boolean; display?: { amount: string } } };
  cancellation_policy: string[];
}

function randomSuffix(len = 6): string {
  let out = "";
  while (out.length < len) out += Math.random().toString(36).slice(2);
  return out.slice(0, len);
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/'/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

// Matches only the placeholder keys emptyTarget() generates - never a real
// saved key - so a validated new target's key gets upgraded to a readable
// slug exactly once, and an existing target's key is never touched.
function isAutoKey(key: string): boolean {
  return /^target-[a-z0-9]{6,8}$/.test(key);
}

function emptyTarget(): Target {
  return {
    key: `target-${randomSuffix()}`,
    venue_name: "",
    request: "",
    venue_id: null,
    venue_display: null,
    enabled: true,
    dry_run: true, // new targets default to notify mode until checked
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

function ValidationPanel({ result }: { result: ValidationResult }) {
  return (
    <div className="validation-panel">
      {result.venue && (
        <div className="validation-line success">
          ✓ Venue: {result.venue.name}
          {result.venue.address ? ` — ${result.venue.address}` : ""}
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
          {result.criteria.notes && <div className="notes-hint">Note: {result.criteria.notes}</div>}
        </div>
      )}
      {result.criteria_error && (
        <div className="validation-line error">
          ✗ Couldn&apos;t parse request: {result.criteria_error}
        </div>
      )}
      {result.venue && result.criteria && (
        <div className="validation-line">
          {result.cancellation_preview && result.cancellation_preview.length > 0 ? (
            <>
              <strong>Cancellation terms preview:</strong> {result.cancellation_preview[0]}
            </>
          ) : (
            <span className="notes-hint">{result.cancellation_preview_note}</span>
          )}
        </div>
      )}
    </div>
  );
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
  const [serverTargets, setServerTargets] = useState<Target[] | null>(null);
  const [sha, setSha] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editingKeys, setEditingKeys] = useState<Set<string>>(new Set());
  const [checkingKey, setCheckingKey] = useState<string | null>(null);
  const [saveMessages, setSaveMessages] = useState<
    Record<string, { text: string; kind: "success" | "error" } | undefined>
  >({});
  const [validationResults, setValidationResults] = useState<Record<string, ValidationResult>>({});
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
    setServerTargets(data.targets);
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
    if (!confirm(`Remove target "${targets[index].key}"?`)) return;
    setTargets(targets.filter((_, i) => i !== index));
  }

  function addTarget() {
    const t = emptyTarget();
    setTargets((prev) => [t, ...(prev || [])]);
    setEditingKeys((prev) => new Set(prev).add(t.key));
    requestAnimationFrame(() => {
      document.getElementById(`target-venue-${t.key}`)?.focus();
    });
  }

  function editTarget(key: string) {
    setEditingKeys((prev) => new Set(prev).add(key));
  }

  function cancelEdit(index: number) {
    if (!targets) return;
    const t = targets[index];
    setEditingKeys((prev) => {
      const next = new Set(prev);
      next.delete(t.key);
      return next;
    });
    const original = serverTargets?.find((x) => x.key === t.key);
    if (original) {
      const next = [...targets];
      next[index] = original;
      setTargets(next);
    } else {
      setTargets(targets.filter((_, i) => i !== index));
    }
  }

  /** The single CTA for a Watching card: validates venue + request (and
   * previews cancellation terms) first, and only saves if both checked out
   * - saving an unvalidated target isn't possible from this button.
   */
  async function checkAndSave(index: number) {
    if (!targets || sha === null) return;
    const t = targets[index];
    setCheckingKey(t.key);
    setSaveMessages((m) => ({ ...m, [t.key]: undefined }));

    const res = await fetch("/api/validate-target", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ venue_name: t.venue_name, request: t.request }),
    });
    const data: ValidationResult = await res.json();
    setValidationResults((v) => ({ ...v, [t.key]: data }));

    if (!data.venue || !data.criteria) {
      setCheckingKey(null);
      setSaveMessages((m) => ({
        ...m,
        [t.key]: { text: "Fix the issue(s) above before saving.", kind: "error" },
      }));
      return;
    }

    const patch: Partial<Target> = {
      venue_id: data.venue.id,
      venue_display: [data.venue.name, data.venue.address || data.venue.neighborhood]
        .filter(Boolean)
        .join(" — "),
    };
    let newKey = t.key;
    if (isAutoKey(t.key)) {
      const dayPart = data.criteria.days_of_week.length === 1 ? slugify(data.criteria.days_of_week[0]) : "";
      const base = [slugify(data.venue.name), dayPart].filter(Boolean).join("-") || slugify(data.venue.name);
      const others = new Set(targets.filter((x) => x.key !== t.key).map((x) => x.key));
      let candidate = base;
      let n = 2;
      while (others.has(candidate)) candidate = `${base}-${n++}`;
      newKey = candidate;
      patch.key = candidate;
    }

    const patchedTarget = { ...t, ...patch };
    const patchedTargets = targets.map((x, idx) => (idx === index ? patchedTarget : x));
    setTargets(patchedTargets);

    if (newKey !== t.key) {
      setEditingKeys((prev) => {
        if (!prev.has(t.key)) return prev;
        const next = new Set(prev);
        next.delete(t.key);
        next.add(newKey);
        return next;
      });
      setValidationResults((v) => {
        const { [t.key]: moved, ...rest } = v;
        return moved ? { ...rest, [newKey]: moved } : v;
      });
    }

    const saveRes = await fetch("/api/targets", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        targets: patchedTargets,
        sha,
        message: `Update target "${newKey}" via web UI`,
      }),
    });
    const saveData = await saveRes.json();
    setCheckingKey(null);
    if (!saveRes.ok) {
      setSaveMessages((m) => ({ ...m, [newKey]: { text: saveData.error || "Save failed", kind: "error" } }));
      return;
    }
    setSaveMessages((m) => ({
      ...m,
      [newKey]: { text: "Checked and saved - bot redeploys in ~1-2 min.", kind: "success" },
    }));
    setEditingKeys((prev) => {
      const next = new Set(prev);
      next.delete(newKey);
      return next;
    });
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
            Reservations the bot is watching. "Check &amp; Save" validates the venue and request
            before committing every change on the page to GitHub, which redeploys the bot.
          </p>
        </div>
        <button className="ghost logout-button" onClick={logout}>
          Log out
        </button>
      </div>

      <div className="action-toolbar">
        <button className="primary" onClick={addTarget}>
          + Add target
        </button>
      </div>

      {targets.length === 0 && <div className="empty-state">No targets yet - add one above.</div>}

      {watching.map(({ t, i }) => {
        const isEditing = editingKeys.has(t.key);
        const message = saveMessages[t.key];
        const result = validationResults[t.key];

        if (!isEditing) {
          return (
            <div className="card" key={t.key}>
              <div className="target-header">
                <div className="booked-title">
                  <strong>{t.venue_name || "(unnamed venue)"}</strong>
                  <span className="booked-key">{t.key}</span>
                </div>
                <StatusBadge target={t} />
              </div>
              {t.venue_display && <div className="notes-hint">{t.venue_display}</div>}
              <div className="notes-hint">{t.request}</div>
              {result && <ValidationPanel result={result} />}
              <div className="card-actions">
                <div className="card-actions-left">
                  <button className="danger" onClick={() => removeTarget(i)}>
                    Remove
                  </button>
                </div>
                <button onClick={() => editTarget(t.key)}>Edit</button>
              </div>
              {message && <div className={`status-message ${message.kind}`}>{message.text}</div>}
            </div>
          );
        }

        const isNew = !serverTargets?.some((x) => x.key === t.key);

        return (
          <div className="card" key={t.key}>
            <div className="target-header">
              <div className="target-key-display">{t.key}</div>
              <StatusBadge target={t} />
            </div>

            <div className="field-row">
              <label>Venue name</label>
              <div>
                <input
                  id={`target-venue-${t.key}`}
                  type="text"
                  placeholder="e.g. Pizza 4P's Brooklyn"
                  value={t.venue_name}
                  onChange={(e) => updateTarget(i, { venue_name: e.target.value })}
                />
                {t.venue_display && !result?.venue_error && (
                  <div className="notes-hint">{t.venue_display}</div>
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
              <label>Mode</label>
              <div className="mode-toggle">
                <label className="toggle-label">
                  <input
                    type="radio"
                    name={`mode-${t.key}`}
                    checked={t.dry_run === true}
                    onChange={() => updateTarget(i, { dry_run: true })}
                  />
                  Notify mode - email me when a match opens, don&apos;t book
                </label>
                <label className="toggle-label">
                  <input
                    type="radio"
                    name={`mode-${t.key}`}
                    checked={t.dry_run !== true}
                    onChange={() => updateTarget(i, { dry_run: false })}
                  />
                  Book mode - book automatically
                </label>
              </div>
            </div>

            {result && (
              <div className="validation-panel">
                {result.venue && (
                  <div className="validation-line success">
                    ✓ Venue: {result.venue.name}
                    {result.venue.address ? ` — ${result.venue.address}` : ""}
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
                  <div className="validation-line error">
                    ✗ Couldn&apos;t parse request: {result.criteria_error}
                  </div>
                )}
                {result.venue && result.criteria && (
                  <div className="validation-line">
                    {result.cancellation_preview && result.cancellation_preview.length > 0 ? (
                      <>
                        <strong>Cancellation terms preview:</strong> {result.cancellation_preview[0]}
                      </>
                    ) : (
                      <span className="notes-hint">{result.cancellation_preview_note}</span>
                    )}
                  </div>
                )}
              </div>
            )}

            <div className="card-actions">
              <div className="card-actions-left">
                {!isNew && <button onClick={() => cancelEdit(i)}>Cancel</button>}
                <button className="danger" onClick={() => removeTarget(i)}>
                  Remove
                </button>
              </div>
              <button className="primary" onClick={() => checkAndSave(i)} disabled={checkingKey === t.key}>
                {checkingKey === t.key ? "Checking & saving..." : "Check & Save"}
              </button>
            </div>
            {message && <div className={`status-message ${message.kind}`}>{message.text}</div>}
          </div>
        );
      })}

      {booked.length > 0 && (
        <>
          <h2 className="section-heading">Booked</h2>
          {booked.map(({ t, i }) => {
            const liveRes = liveReservations?.find((r) => r.reservation_id === t.booking!.reservation_id);
            return (
              <div className="card card-booked" key={t.key}>
                <div className="target-header">
                  <div className="booked-title">
                    <strong>{t.venue_name}</strong>
                    <span className="booked-key">{t.key}</span>
                  </div>
                  <StatusBadge target={t} />
                </div>

                {t.venue_display && <div className="notes-hint">{t.venue_display}</div>}
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

                <div className="card-actions card-actions-end">
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
