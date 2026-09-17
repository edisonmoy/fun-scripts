// Thin client for Resy's private, undocumented consumer API - the
// TypeScript counterpart to resy-sniper/resy_api.py, used here for the
// webapp's "validate a target" and "cancel a booked reservation" flows.
// Kept minimal (only what the webapp needs) rather than a full port.

const BASE_URL = "https://api.resy.com";
const USER_AGENT =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";

function resyHeaders(): Record<string, string> {
  const authToken = process.env.RESY_AUTH_TOKEN;
  const apiKey = process.env.RESY_API_KEY;
  if (!authToken || !apiKey) {
    throw new Error("RESY_AUTH_TOKEN / RESY_API_KEY is not set");
  }
  return {
    Authorization: `ResyAPI api_key="${apiKey}"`,
    "x-resy-auth-token": authToken,
    "x-resy-universal-auth": authToken,
    "User-Agent": USER_AGENT,
    Accept: "application/json",
    Origin: "https://resy.com",
    Referer: "https://resy.com/",
    "X-Origin": "https://resy.com",
  };
}

export interface ResolvedVenue {
  id: number;
  name: string;
  neighborhood: string | null;
  city: string | null;
}

export async function findVenue(name: string): Promise<ResolvedVenue> {
  const resp = await fetch(`${BASE_URL}/3/venuesearch/search`, {
    method: "POST",
    headers: { ...resyHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ query: name, per_page: 5 }),
  });
  if (!resp.ok) {
    throw new Error(`Resy venue search failed (${resp.status}): ${await resp.text()}`);
  }
  const data = await resp.json();
  const hits = data?.search?.hits ?? [];
  if (hits.length === 0) {
    throw new Error(`No Resy venue found for "${name}"`);
  }
  const hit = hits[0];
  return {
    id: hit.id.resy,
    name: hit.name,
    neighborhood: hit.neighborhood ?? null,
    city: hit.location?.name ?? null,
  };
}

export interface CancellationFee {
  amount: number;
  applies: boolean;
  display?: { amount: string };
}

export interface LiveReservation {
  reservation_id: number;
  resy_token: string;
  day: string;
  time_slot: string;
  num_seats: number;
  venue: { id: number };
  cancellation: {
    allowed: boolean;
    date_refund_cut_off: string | null;
    fee?: CancellationFee;
  };
  cancellation_policy: string[];
}

export async function listReservations(): Promise<LiveReservation[]> {
  const resp = await fetch(`${BASE_URL}/3/user/reservations?type=upcoming`, {
    headers: resyHeaders(),
  });
  if (!resp.ok) {
    throw new Error(`Resy reservations fetch failed (${resp.status}): ${await resp.text()}`);
  }
  const data = await resp.json();
  return data.reservations ?? [];
}

/** Looks up the reservation's current resy_token (it rotates - never
 * trust a token stored earlier) and cancels it. Throws if the
 * reservation can't be found or Resy rejects the cancellation.
 */
export async function cancelReservation(reservationId: number): Promise<void> {
  const reservations = await listReservations();
  const match = reservations.find((r) => r.reservation_id === reservationId);
  if (!match) {
    throw new Error(`Reservation ${reservationId} not found in upcoming reservations`);
  }

  const resp = await fetch(`${BASE_URL}/3/cancel`, {
    method: "POST",
    headers: {
      ...resyHeaders(),
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({ resy_token: match.resy_token }).toString(),
  });
  if (!resp.ok) {
    throw new Error(`Resy cancel failed (${resp.status}): ${await resp.text()}`);
  }
}
