import { NextResponse } from "next/server";
import { listReservations } from "@/lib/resy";

// Live cancellation terms are time-sensitive (fee eligibility flips at the
// cutoff), so this always hits Resy fresh rather than reading anything
// cached in targets.json. Trimmed to just what the dashboard shows - the
// raw Resy response includes unrelated stuff like other guests' names.
export async function GET() {
  try {
    const reservations = await listReservations();
    const trimmed = reservations.map((r) => ({
      reservation_id: r.reservation_id,
      cancellation: r.cancellation,
      cancellation_policy: r.cancellation_policy,
    }));
    return NextResponse.json({ reservations: trimmed });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
