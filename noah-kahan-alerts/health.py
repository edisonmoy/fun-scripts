import json
import os

HEALTH_PATH = os.path.join(os.path.dirname(__file__), "data", "scraper_health.json")


def _load():
    if not os.path.exists(HEALTH_PATH):
        return {}
    with open(HEALTH_PATH) as f:
        return json.load(f)


def _save(state):
    os.makedirs(os.path.dirname(HEALTH_PATH), exist_ok=True)
    with open(HEALTH_PATH, "w") as f:
        json.dump(state, f, indent=2)


def record_outcome(source, status):
    """Update the consecutive blocked/error streak for `source`.

    Returns (consecutive_count, just_recovered) so the caller can decide
    whether to escalate (streak crosses a threshold) or resolve (was
    failing, is now "ok").
    """
    state = _load()
    entry = state.get(source, {"consecutive_blocked": 0})
    just_recovered = status == "ok" and entry["consecutive_blocked"] > 0

    entry["consecutive_blocked"] = (
        entry["consecutive_blocked"] + 1 if status in ("blocked", "error") else 0
    )

    state[source] = entry
    _save(state)
    return entry["consecutive_blocked"], just_recovered
