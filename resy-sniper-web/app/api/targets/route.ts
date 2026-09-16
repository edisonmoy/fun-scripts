import { NextRequest, NextResponse } from "next/server";
import { Target, fetchTargets, saveTargets } from "@/lib/github";

export async function GET() {
  try {
    const { targets, sha } = await fetchTargets();
    return NextResponse.json({ targets, sha });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}

function validate(targets: Target[]): string | null {
  if (!Array.isArray(targets)) return "targets must be an array";

  const keys = targets.map((t) => t.key);
  const dupes = keys.filter((k, i) => keys.indexOf(k) !== i);
  if (dupes.length > 0) return `duplicate keys: ${[...new Set(dupes)].join(", ")}`;

  for (const t of targets) {
    if (!t.key?.trim()) return "every target needs a key";
    if (!t.venue_name?.trim()) return `target "${t.key}" needs a venue name`;
    if (!t.request?.trim()) return `target "${t.key}" needs a request description`;
  }
  return null;
}

export async function PUT(req: NextRequest) {
  try {
    const body = await req.json();
    const targets: Target[] = body.targets;
    const sha: string = body.sha;
    const message: string = body.message || "Update resy-sniper targets";

    const error = validate(targets);
    if (error) {
      return NextResponse.json({ error }, { status: 400 });
    }

    await saveTargets(targets, sha, message);
    return NextResponse.json({ ok: true });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
