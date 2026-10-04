"""Turns a free-text booking request ("Saturday dinner for 2, flexible on
time between 5-9pm") into structured search criteria via the Claude API.
Runs once at process startup, not a hot path - a single small extraction
call, so latency/cost are a non-issue (a few seconds, fractions of a cent).
"""
import logging
from datetime import date, datetime, timedelta
from typing import Annotated, List, Literal
from zoneinfo import ZoneInfo

import anthropic
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

# A small, well-specified extraction - the fast model handles it, and the
# validation on BookingCriteria rejects anything malformed rather than
# letting it through. Keep in lockstep with resy-sniper-web/lib/claude.ts.
MODEL = "claude-haiku-4-5"

# 24h zero-padded "HH:MM". in_time_window() compares these as strings, so
# "7:00" or "19:00:00" would silently match the wrong slots - reject them.
HH_MM_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
ISO_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

# Relative dates ("this Thursday", "10/22") are resolved against today in
# the user's timezone, not the server's UTC clock.
USER_TZ = ZoneInfo("America/New_York")

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_WEEKDAY_INDEX = {name: i for i, name in enumerate(WEEKDAYS)}

DayName = Literal[
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
]

SYSTEM_PROMPT = (
    "Extract restaurant reservation search criteria from a free-text request. "
    "time_window_start/time_window_end are 24h \"HH:MM\" strings. If the "
    "request names an explicit lookahead (e.g. \"next 2 months\"), convert it "
    "to whole weeks; otherwise default lookahead_weeks to 8. If no time range "
    "is given, default to a sensible window for the named meal (breakfast "
    "07:00-10:00, lunch 11:30-14:00, dinner 17:00-21:00). If no days of week "
    "are named at all (fully flexible), include all seven. If the request "
    "names specific calendar dates or a date range (\"10/22-24\", \"Oct 22 to "
    "24\", \"this Thursday\", \"tomorrow\"), resolve them against the given "
    "today's date and list every date in specific_dates as YYYY-MM-DD - a "
    "date without a year means its next occurrence on or after today - and "
    "set days_of_week to those dates' weekdays; otherwise leave specific_dates "
    "empty. Recurring phrasing (\"any Friday\", \"Saturdays\") is days_of_week, "
    "not specific_dates. Set allow_same_day to true only if the request "
    "explicitly says it's fine to book even on a day that already has another "
    "reservation (\"even if I have another reservation that day\", \"double "
    "booking is ok\"); otherwise false. notes should flag anything you could "
    "not represent "
    "in the structured fields - a neighborhood preference, a budget - so a "
    "human reviews it rather than it being silently dropped."
)


class BookingCriteria(BaseModel):
    party_size: int = Field(ge=1, le=20)
    days_of_week: List[DayName] = Field(min_length=1)
    time_window_start: str = Field(pattern=HH_MM_PATTERN)
    time_window_end: str = Field(pattern=HH_MM_PATTERN)
    lookahead_weeks: int = Field(ge=1, le=52)
    # When set, the only dates searched - days_of_week/lookahead_weeks are
    # ignored. Without this, "10/22-24" became "every day for 8 weeks".
    # Required (no default) so the model must always answer it - [] when the
    # request has no specific dates.
    specific_dates: List[Annotated[str, Field(pattern=ISO_DATE_PATTERN)]]
    # Opts this target out of the bot's one-reservation-per-day rule.
    allow_same_day: bool
    notes: str

    @model_validator(mode="after")
    def _window_in_order(self):
        if self.time_window_start > self.time_window_end:
            raise ValueError("time_window_start must not be after time_window_end")
        return self

    @model_validator(mode="after")
    def _real_dates(self):
        for d in self.specific_dates:
            date.fromisoformat(d)  # rejects e.g. 2026-02-30
        return self

    def candidate_dates(self, today=None):
        """ISO date strings to search, soonest first.

        With specific_dates, exactly those that haven't passed. Otherwise
        every matching weekday within the lookahead window - a window of
        exactly lookahead_weeks*7 days always contains each weekday exactly
        lookahead_weeks times, regardless of what weekday today is.
        """
        today = today or date.today()
        if self.specific_dates:
            return sorted({d for d in self.specific_dates if date.fromisoformat(d) >= today})
        targets = {_WEEKDAY_INDEX[d] for d in self.days_of_week}
        horizon_days = self.lookahead_weeks * 7
        return [
            d.isoformat()
            for offset in range(horizon_days)
            if (d := today + timedelta(days=offset)).weekday() in targets
        ]

    def in_time_window(self, hh_mm):
        return self.time_window_start <= hh_mm <= self.time_window_end


def user_message(request_text, today):
    """Keep in lockstep with userMessage() in resy-sniper-web/lib/claude.ts."""
    return f"Today is {today:%A}, {today.isoformat()}.\n\nRequest: {request_text}"


def parse(request_text, today=None):
    today = today or datetime.now(USER_TZ).date()
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message(request_text, today)}],
        output_format=BookingCriteria,
    )
    criteria = response.parsed_output
    logger.info("parsed booking request %r -> %s", request_text, criteria)
    return criteria
