import json
import os
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def _path(name):
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, f"{name}.jsonl")


def append_record(name, record):
    """Append one JSON record to data/<name>.jsonl, stamped with the current time."""
    record = {**record, "checked_at": datetime.now(timezone.utc).isoformat()}
    with open(_path(name), "a") as f:
        f.write(json.dumps(record) + "\n")
    return record


def load_records(name):
    path = _path(name)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def running_floor(name, field="price_per_ticket"):
    """Lowest value seen for `field` across all prior records, before the current check."""
    records = load_records(name)
    values = [r[field] for r in records if r.get(field) is not None]
    return min(values) if values else None
