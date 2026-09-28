// Turns a free-text booking request into structured search criteria via
// the Claude API - the TypeScript counterpart to resy-sniper/request_parser.py,
// used by the "validate a target" flow so the webapp can show what the
// bot will actually watch for before the user saves it.

import Anthropic from "@anthropic-ai/sdk";
import { zodOutputFormat } from "@anthropic-ai/sdk/helpers/zod";
import { z } from "zod";

// A small, well-specified extraction - the fast model handles it, and the
// validation on BookingCriteriaSchema rejects anything malformed rather than
// letting it through. Keep in lockstep with resy-sniper/request_parser.py.
const MODEL = "claude-haiku-4-5";

// 24h zero-padded "HH:MM". inTimeWindow() compares these as strings, so
// "7:00" or "19:00:00" would silently match the wrong slots - reject them.
const HH_MM = /^([01]\d|2[0-3]):[0-5]\d$/;

const DAY_NAMES = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
] as const;

// Keep this in lockstep with resy-sniper/request_parser.py's SYSTEM_PROMPT -
// both sides must parse the same request text the same way.
const SYSTEM_PROMPT =
  "Extract restaurant reservation search criteria from a free-text request. " +
  'time_window_start/time_window_end are 24h "HH:MM" strings. If the ' +
  'request names an explicit lookahead (e.g. "next 2 months"), convert it ' +
  "to whole weeks; otherwise default lookahead_weeks to 8. If no time range " +
  "is given, default to a sensible window for the named meal (breakfast " +
  "07:00-10:00, lunch 11:30-14:00, dinner 17:00-21:00). If no days of week " +
  "are named at all (fully flexible), include all seven. notes should flag " +
  "anything you could not represent in the structured fields - a specific " +
  "single date, a neighborhood preference, a budget - so a human reviews it " +
  "rather than it being silently dropped.";

export const BookingCriteriaSchema = z
  .object({
    party_size: z.number().int().min(1).max(20),
    days_of_week: z.array(z.enum(DAY_NAMES)).min(1),
    time_window_start: z.string().regex(HH_MM),
    time_window_end: z.string().regex(HH_MM),
    lookahead_weeks: z.number().int().min(1).max(52),
    notes: z.string(),
  })
  .refine((c) => c.time_window_start <= c.time_window_end, {
    message: "time_window_start must not be after time_window_end",
  });

export type BookingCriteria = z.infer<typeof BookingCriteriaSchema>;

export async function parseRequest(requestText: string): Promise<BookingCriteria> {
  const client = new Anthropic();
  const response = await client.messages.parse({
    model: MODEL,
    max_tokens: 1024,
    system: SYSTEM_PROMPT,
    messages: [{ role: "user", content: requestText }],
    output_config: { format: zodOutputFormat(BookingCriteriaSchema) },
  });
  if (!response.parsed_output) {
    throw new Error("Claude did not return a parseable result");
  }
  return response.parsed_output;
}

// TS port of BookingCriteria.candidate_dates() / .in_time_window() from
// request_parser.py - used to preview whether a slot is currently
// available (and its cancellation terms) before saving a target.

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/** ISO date strings for every matching weekday within the lookahead
 * window, soonest first, capped at `limit` entries (the caller is
 * probing Resy live per date - keep this bounded for latency).
 */
export function candidateDates(criteria: BookingCriteria, limit = 12): string[] {
  const targets = new Set(criteria.days_of_week.map((d) => DAY_NAMES.indexOf(d)));
  const horizonDays = criteria.lookahead_weeks * 7;
  const dates: string[] = [];
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  for (let offset = 0; offset < horizonDays && dates.length < limit; offset++) {
    const d = new Date(today);
    d.setDate(d.getDate() + offset);
    // getDay(): Sun=0..Sat=6 - convert to Mon=0..Sun=6 to match DAY_NAMES
    const weekday = (d.getDay() + 6) % 7;
    if (targets.has(weekday)) dates.push(isoDate(d));
  }
  return dates;
}

export function inTimeWindow(criteria: BookingCriteria, hhmm: string): boolean {
  return criteria.time_window_start <= hhmm && hhmm <= criteria.time_window_end;
}
