// Pure matching logic for venue resolution - kept free of network calls so
// it can be unit tested. See lib/venue.ts for the flow that uses it.

export interface IdentifiedRestaurant {
  found: boolean;
  name: string;
  resy_search_query: string;
  street_address: string | null;
  city: string | null;
  state_or_region: string | null;
  postal_code: string | null;
  country: string | null;
  notes: string;
}

export interface VenueCandidate {
  id: number;
  name: string;
  neighborhood: string | null;
  street_address: string | null;
  locality: string | null;
  region: string | null;
  postal_code: string | null;
}

// Words that say nothing about which restaurant it is - dropped before
// comparing names, so "The Coop at Double Chicken Please" still matches
// "Double Chicken Please" and "Lei Wine Bar" matches "Lei".
const FILLER = new Set([
  "the", "a", "an", "and", "at", "of", "by", "restaurant", "bar", "wine", "winebar",
  "cafe", "kitchen", "nyc", "ny", "new", "york",
]);

const US_STATES: Record<string, string> = {
  "new york": "NY", "new jersey": "NJ", "connecticut": "CT", "california": "CA",
  "massachusetts": "MA", "pennsylvania": "PA", "illinois": "IL", "florida": "FL",
  "texas": "TX", "district of columbia": "DC",
};

export function normalizeTokens(text: string | null | undefined): string[] {
  return (text ?? "")
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/'/g, "")
    .split(/[^a-z0-9]+/)
    .filter((t) => t && !FILLER.has(t));
}

/** 0..1: how well two restaurant names match. 1 when one name's
 * meaningful words are all contained in the other's. */
export function nameScore(a: string, b: string): number {
  const ta = new Set(normalizeTokens(a));
  const tb = new Set(normalizeTokens(b));
  if (ta.size === 0 || tb.size === 0) return 0;
  const shared = [...ta].filter((t) => tb.has(t)).length;
  return shared / Math.min(ta.size, tb.size);
}

function normState(s: string | null | undefined): string | null {
  if (!s) return null;
  const t = s.trim().toLowerCase();
  if (!t) return null;
  return US_STATES[t] ?? t.toUpperCase();
}

function streetNumber(addr: string | null | undefined): string | null {
  return addr?.trim().match(/^(\d+)/)?.[1] ?? null;
}

function zip5(z: string | null | undefined): string | null {
  return z?.trim().match(/^(\d{5})/)?.[1] ?? z?.trim() ?? null;
}

export interface ScoredCandidate {
  candidate: VenueCandidate;
  nameScore: number;
  sameRegion: boolean | null; // null = nothing to compare against
  samePostal: boolean | null;
  sameStreetNumber: boolean | null;
}

export function scoreCandidate(
  identified: IdentifiedRestaurant,
  candidate: VenueCandidate
): ScoredCandidate {
  const idState = normState(identified.state_or_region);
  const candState = normState(candidate.region);
  const idZip = zip5(identified.postal_code);
  const candZip = zip5(candidate.postal_code);
  const idNum = streetNumber(identified.street_address);
  const candNum = streetNumber(candidate.street_address);
  return {
    candidate,
    nameScore: nameScore(identified.name, candidate.name),
    sameRegion: idState && candState ? idState === candState : null,
    samePostal: idZip && candZip ? idZip === candZip : null,
    sameStreetNumber: idNum && candNum ? idNum === candNum : null,
  };
}

/** A candidate is accepted only if its name matches AND nothing about its
 * location contradicts the identified restaurant (different state,
 * postcode, or street number). Among accepted ones, a confirmed address
 * match wins over a name-only match. */
export function isAcceptable(s: ScoredCandidate): boolean {
  if (s.nameScore < 0.6) return false;
  if (s.sameRegion === false) return false;
  if (s.samePostal === false && s.sameStreetNumber === false) return false;
  return true;
}

function rank(s: ScoredCandidate): number {
  return (
    s.nameScore +
    (s.samePostal ? 1 : 0) +
    (s.sameStreetNumber ? 1 : 0) +
    (s.sameRegion ? 0.5 : 0)
  );
}

export function pickBestCandidate(
  identified: IdentifiedRestaurant,
  candidates: VenueCandidate[]
): { best: ScoredCandidate | null; scored: ScoredCandidate[] } {
  const scored = candidates.map((c) => scoreCandidate(identified, c));
  const acceptable = scored.filter(isAcceptable).sort((a, b) => rank(b) - rank(a));
  return { best: acceptable[0] ?? null, scored };
}

export function formatCandidateAddress(c: VenueCandidate): string | null {
  const parts = [c.street_address, c.locality, c.region].filter(Boolean);
  if (parts.length === 0) return c.neighborhood;
  return c.postal_code ? `${parts.join(", ")} ${c.postal_code}` : parts.join(", ");
}
