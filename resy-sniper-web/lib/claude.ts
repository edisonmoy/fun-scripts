// Turns a free-text booking request into structured search criteria via
// the Claude API - the TypeScript counterpart to resy-sniper/request_parser.py,
// used by the "validate a target" flow so the webapp can show what the
// bot will actually watch for before the user saves it.

import Anthropic from "@anthropic-ai/sdk";
import { zodOutputFormat } from "@anthropic-ai/sdk/helpers/zod";
import { z } from "zod";

const MODEL = "claude-opus-5";

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

export const BookingCriteriaSchema = z.object({
  party_size: z.number().int(),
  days_of_week: z.array(z.enum(DAY_NAMES)),
  time_window_start: z.string(),
  time_window_end: z.string(),
  lookahead_weeks: z.number().int(),
  notes: z.string(),
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
