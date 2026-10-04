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
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

// Relative dates ("this Thursday", "10/22") are resolved against today in
// the user's timezone, not the server's UTC clock.
const USER_TZ = "America/New_York";

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
  "are named at all (fully flexible), include all seven. If the request " +
  'names specific calendar dates or a date range ("10/22-24", "Oct 22 to ' +
  '24", "this Thursday", "tomorrow"), resolve them against the given ' +
  "today's date and list every date in specific_dates as YYYY-MM-DD - a " +
  "date without a year means its next occurrence on or after today - and " +
  "set days_of_week to those dates' weekdays; otherwise leave specific_dates " +
  'empty. Recurring phrasing ("any Friday", "Saturdays") is days_of_week, ' +
  "not specific_dates. notes should flag anything you could not represent " +
  "in the structured fields - a neighborhood preference, a budget - so a " +
  "human reviews it rather than it being silently dropped.";

function isRealDate(iso: string): boolean {
  const d = new Date(`${iso}T00:00:00Z`);
  return !isNaN(d.getTime()) && d.toISOString().slice(0, 10) === iso;
}

export const BookingCriteriaSchema = z
  .object({
    party_size: z.number().int().min(1).max(20),
    days_of_week: z.array(z.enum(DAY_NAMES)).min(1),
    time_window_start: z.string().regex(HH_MM),
    time_window_end: z.string().regex(HH_MM),
    lookahead_weeks: z.number().int().min(1).max(52),
    // When non-empty, the only dates searched - days_of_week/lookahead_weeks
    // are ignored. Without this, "10/22-24" became "every day for 8 weeks".
    specific_dates: z.array(z.string().regex(ISO_DATE).refine(isRealDate, "not a real date")),
    notes: z.string(),
  })
  .refine((c) => c.time_window_start <= c.time_window_end, {
    message: "time_window_start must not be after time_window_end",
  });

export type BookingCriteria = z.infer<typeof BookingCriteriaSchema>;

/** Today's date in USER_TZ as { iso: "YYYY-MM-DD", weekday: "Sunday" }. */
export function todayInUserTz(now: Date = new Date()): { iso: string; weekday: string } {
  const iso = new Intl.DateTimeFormat("en-CA", { timeZone: USER_TZ }).format(now);
  const weekday = new Intl.DateTimeFormat("en-US", { timeZone: USER_TZ, weekday: "long" }).format(now);
  return { iso, weekday };
}

/** Keep in lockstep with user_message() in resy-sniper/request_parser.py. */
export function userMessage(requestText: string, today = todayInUserTz()): string {
  return `Today is ${today.weekday}, ${today.iso}.\n\nRequest: ${requestText}`;
}

export async function parseRequest(requestText: string): Promise<BookingCriteria> {
  const client = new Anthropic();
  const response = await client.messages.parse({
    model: MODEL,
    max_tokens: 1024,
    system: SYSTEM_PROMPT,
    messages: [{ role: "user", content: userMessage(requestText) }],
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

/** ISO date strings to search, soonest first, capped at `limit` entries
 * (the caller is probing Resy live per date - keep this bounded for
 * latency). With specific_dates, exactly those that haven't passed;
 * otherwise every matching weekday within the lookahead window.
 */
export function candidateDates(criteria: BookingCriteria, limit = 12): string[] {
  if (criteria.specific_dates.length > 0) {
    const today = todayInUserTz().iso;
    return [...new Set(criteria.specific_dates)]
      .filter((d) => d >= today)
      .sort()
      .slice(0, limit);
  }
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
