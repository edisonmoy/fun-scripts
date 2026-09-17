import { NextRequest, NextResponse } from "next/server";
import { parseRequest } from "@/lib/claude";
import { findVenue } from "@/lib/resy";

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
    venue?: Awaited<ReturnType<typeof findVenue>>;
    venue_error?: string;
    criteria?: Awaited<ReturnType<typeof parseRequest>>;
    criteria_error?: string;
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

  return NextResponse.json(body);
}
