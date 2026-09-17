"""Commits an updated targets.json back to GitHub once a target books.

This is what makes booking status survive a redeploy (Fly's container
disk is ephemeral - nothing written locally lives past the next deploy)
and is how the management webapp learns a target booked. Best-effort by
design: if this commit fails, the reservation itself already succeeded
and isn't undone - the only cost is the bot not remembering it locally
until the next successful sync, and even then Resy won't offer the same
held slot again, so there's no double-booking risk either way.
"""
import base64
import json
import logging

import requests

import config

logger = logging.getLogger(__name__)

OWNER = "edisonmoy"
REPO = "fun-scripts"
PATH = "resy-sniper/targets.json"
BRANCH = "master"
BASE_URL = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{PATH}"


def _headers():
    if not config.GITHUB_TOKEN:
        raise RuntimeError("RESY_GITHUB_TOKEN is not set")
    return {
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _fetch():
    resp = requests.get(f"{BASE_URL}?ref={BRANCH}", headers=_headers(), timeout=10)
    resp.raise_for_status()
    data = resp.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return json.loads(content), data["sha"]


def record_booking(key, day, time, party_size, reservation_id, max_retries=2):
    """Set the `booking` field on the target with this key in the GitHub-
    hosted targets.json. Retries once on a stale-sha conflict (another
    write landed between our fetch and our commit).
    """
    for attempt in range(max_retries + 1):
        targets, sha = _fetch()

        match = next((t for t in targets if t.get("key") == key), None)
        if match is None:
            logger.warning("record_booking: key %r not found in targets.json, skipping", key)
            return
        match["booking"] = {
            "day": day,
            "time": time,
            "party_size": party_size,
            "reservation_id": reservation_id,
        }

        body = json.dumps(targets, indent=2) + "\n"
        content = base64.b64encode(body.encode("utf-8")).decode("utf-8")
        resp = requests.put(
            BASE_URL,
            headers=_headers(),
            json={
                "message": f"Record booking for {key}",
                "content": content,
                "sha": sha,
                "branch": BRANCH,
            },
            timeout=10,
        )
        if resp.status_code == 409 and attempt < max_retries:
            logger.warning(
                "record_booking: sha conflict, retrying (%d/%d)", attempt + 1, max_retries
            )
            continue
        resp.raise_for_status()
        logger.info("[%s] booking recorded in targets.json", key)
        return
