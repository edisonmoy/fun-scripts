import { NextRequest, NextResponse } from "next/server";
import { fetchTargets, saveTargets } from "@/lib/github";
import { cancelReservation } from "@/lib/resy";

export async function POST(req: NextRequest) {
  const { key, reservation_id } = await req.json();
  if (!key || !reservation_id) {
    return NextResponse.json({ error: "key and reservation_id are required" }, { status: 400 });
  }

  // Cancel on Resy first - that's the real, consequential action. Only
  // once it succeeds do we touch our own record of it.
  try {
    await cancelReservation(reservation_id);
  } catch (err) {
    return NextResponse.json({ error: `Cancel failed: ${err}` }, { status: 500 });
  }

  try {
    const { targets, sha } = await fetchTargets();
    const match = targets.find((t) => t.key === key);
    if (match) {
      match.booking = null;
    }
    await saveTargets(targets, sha, `Cancel reservation for ${key}`);
  } catch (err) {
    // The cancellation itself already succeeded - don't report this as a
    // failure, just flag that our own record is now stale.
    return NextResponse.json({
      ok: true,
      warning: `Reservation cancelled on Resy, but failed to update targets.json: ${err}`,
    });
  }

  return NextResponse.json({ ok: true });
}
