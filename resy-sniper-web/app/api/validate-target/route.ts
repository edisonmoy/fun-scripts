import { NextRequest, NextResponse } from "next/server";
import { BookingCriteria, candidateDates, inTimeWindow, parseRequest } from "@/lib/claude";
import { findSlots, findVenue, getSlotDetails, ResolvedVenue, slotTime } from "@/lib/resy";

/** Probes a handful of upcoming candidate dates for a slot matching the
 * criteria's time window, and if one exists, fetches its cancellation
 * terms - the same /3/details call the bot makes to get a book_token,
 * just never followed by an actual /3/book. Resy only exposes
 * cancellation/deposit terms per-slot, not at the venue level, so this
 * can come back empty for a fully-booked venue - that's a normal,
 * expected outcome, not an error.
 */
async function previewCancellationPolicy(
  venueId: number,
  criteria: BookingCriteria
): Promise<{ policy: string[] | null; note: string }> {
  const dates = candidateDates(criteria, 12);
  for (const day of dates) {
    let slots;
    try {
      slots = await findSlots(venueId, day, criteria.party_size);
    } catch {
      continue; // a flaky date shouldn't block checking the rest, same as the bot's own polling
    }
    const matching = slots.filter((s) => inTimeWindow(criteria, slotTime(s)));
    if (matching.length === 0) continue;
    try {
      const details = await getSlotDetails(matching[0].config.token, day, criteria.party_size);
      const policy = details.cancellation?.display?.policy ?? null;
      return {
        policy,
        note: policy ? `Preview from the ${day} slot currently open.` : "No cancellation terms returned for this slot.",
      };
    } catch (err) {
      return { policy: null, note: `Found an open slot but couldn't fetch its terms: ${err}` };
    }
  }
  return {
    policy: null,
    note: "No matching slot is open right now to preview terms from - Resy sets these per booking.",
  };
}

export async function POST(req: NextRequest) {
  const { venue_name, request: requestText } = await req.json();

  if (!venue_name?.trim() || !requestText?.trim()) {
    return NextResponse.json({ error: "venue_name and request are both required" }, { status: 400 });
  }

  const [venueResult, criteriaResult] = await Promise.allSettled([
    findVenue(venue_name),
    parseRequest(requestText),
  ]);

  const body: {
    venue?: ResolvedVenue;
    venue_error?: string;
    criteria?: BookingCriteria;
    criteria_error?: string;
    cancellation_preview?: string[] | null;
    cancellation_preview_note?: string;
  } = {};

  if (venueResult.status === "fulfilled") {
    body.venue = venueResult.value;
  } else {
    body.venue_error = String(venueResult.reason);
  }

  if (criteriaResult.status === "fulfilled") {
    body.criteria = criteriaResult.value;
  } else {
    body.criteria_error = String(criteriaResult.reason);
  }

  if (body.venue && body.criteria) {
    try {
      const preview = await previewCancellationPolicy(body.venue.id, body.criteria);
      body.cancellation_preview = preview.policy;
      body.cancellation_preview_note = preview.note;
    } catch (err) {
      body.cancellation_preview_note = `Couldn't check cancellation terms: ${err}`;
    }
  }

  return NextResponse.json(body);
}
