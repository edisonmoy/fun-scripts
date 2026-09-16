"""Turns a free-text booking request ("Saturday dinner for 2, flexible on
time between 5-9pm") into structured search criteria via the Claude API.
Runs once at process startup, not a hot path - a single small extraction
call, so latency/cost are a non-issue (a few seconds, fractions of a cent).
"""
import logging
from datetime import date, timedelta
from typing import List, Literal

import anthropic
from pydantic import BaseModel

logger = logging.getLogger(__name__)

MODEL = "claude-opus-5"

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
    "are named at all (fully flexible), include all seven. notes should flag "
    "anything you could not represent in the structured fields - a specific "
    "single date, a neighborhood preference, a budget - so a human reviews it "
    "rather than it being silently dropped."
)


class BookingCriteria(BaseModel):
    party_size: int
    days_of_week: List[DayName]
    time_window_start: str
    time_window_end: str
    lookahead_weeks: int
    notes: str

    def candidate_dates(self, today=None):
        """ISO date strings for every matching weekday within the lookahead
        window, soonest first.

        A window of exactly lookahead_weeks*7 days always contains each
        weekday exactly lookahead_weeks times, regardless of what weekday
        today is - no off-by-one padding needed.
        """
        today = today or date.today()
        targets = {_WEEKDAY_INDEX[d] for d in self.days_of_week}
        horizon_days = self.lookahead_weeks * 7
        return [
            d.isoformat()
            for offset in range(horizon_days)
            if (d := today + timedelta(days=offset)).weekday() in targets
        ]

    def in_time_window(self, hh_mm):
        return self.time_window_start <= hh_mm <= self.time_window_end


def parse(request_text):
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": request_text}],
        output_format=BookingCriteria,
    )
    criteria = response.parsed_output
    logger.info("parsed booking request %r -> %s", request_text, criteria)
    return criteria
