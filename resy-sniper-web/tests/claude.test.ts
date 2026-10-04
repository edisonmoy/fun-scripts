import { describe, expect, it, vi, afterEach } from "vitest";
import { zodOutputFormat } from "@anthropic-ai/sdk/helpers/zod";
import { BookingCriteria, BookingCriteriaSchema, candidateDates, todayInUserTz, userMessage } from "../lib/claude";

function criteria(overrides: Partial<BookingCriteria> = {}): BookingCriteria {
  return {
    party_size: 2,
    days_of_week: ["Saturday"],
    time_window_start: "17:00",
    time_window_end: "21:00",
    lookahead_weeks: 8,
    specific_dates: [],
    allow_same_day: false,
    notes: "",
    ...overrides,
  };
}

describe("specific dates", () => {
  afterEach(() => vi.useRealTimers());

  it("searches only the specific dates, sorted, ignoring weekdays", () => {
    vi.useFakeTimers({ now: new Date("2026-10-04T16:00:00Z") });
    const c = criteria({ days_of_week: ["Monday"], specific_dates: ["2026-10-24", "2026-10-22", "2026-10-23"] });
    expect(candidateDates(c)).toEqual(["2026-10-22", "2026-10-23", "2026-10-24"]);
  });

  it("drops dates that have passed in New York time", () => {
    // 02:00 UTC on Oct 23 is still Oct 22 in New York
    vi.useFakeTimers({ now: new Date("2026-10-23T02:00:00Z") });
    expect(candidateDates(criteria({ specific_dates: ["2026-10-22", "2026-10-23"] }))).toEqual([
      "2026-10-22",
      "2026-10-23",
    ]);
    vi.setSystemTime(new Date("2026-10-23T16:00:00Z"));
    expect(candidateDates(criteria({ specific_dates: ["2026-10-22", "2026-10-23"] }))).toEqual(["2026-10-23"]);
  });

  it("rejects malformed or impossible dates", () => {
    expect(BookingCriteriaSchema.safeParse(criteria({ specific_dates: ["10/22"] })).success).toBe(false);
    expect(BookingCriteriaSchema.safeParse(criteria({ specific_dates: ["2026-02-30"] })).success).toBe(false);
    expect(BookingCriteriaSchema.safeParse(criteria({ specific_dates: ["2026-10-22"] })).success).toBe(true);
  });

  it("requires specific_dates in the schema sent to the API", () => {
    const schema = zodOutputFormat(BookingCriteriaSchema).schema as { required: string[] };
    expect(schema.required).toContain("specific_dates");
    expect(schema.required).toContain("allow_same_day");
  });

  it("tells the model today's New York date, matching the bot's format", () => {
    const today = todayInUserTz(new Date("2026-10-05T02:00:00Z")); // still Oct 4 in NY
    expect(today).toEqual({ iso: "2026-10-04", weekday: "Sunday" });
    expect(userMessage("Saturday dinner for 2, flexible 5-9pm", today)).toBe(
      "Today is Sunday, 2026-10-04.\n\nRequest: Saturday dinner for 2, flexible 5-9pm"
    );
  });
});
