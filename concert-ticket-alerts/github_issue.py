import logging
import os

import requests

logger = logging.getLogger(__name__)

LABEL = "scraper-blocked"


def _repo():
    return os.environ.get("GITHUB_REPOSITORY", "edisonmoy/fun-scripts")


def _headers():
    token = os.environ["GITHUB_TOKEN"]
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def _api_base():
    return f"https://api.github.com/repos/{_repo()}"


def _find_open_issue(title):
    resp = requests.get(
        f"{_api_base()}/issues",
        headers=_headers(),
        params={"state": "open", "labels": LABEL},
        timeout=15,
    )
    resp.raise_for_status()
    for issue in resp.json():
        if issue["title"] == title:
            return issue
    return None


def escalate(source, diagnostic):
    """Open (or comment on) a GitHub issue so a fix gets picked up.

    This is the trigger for the self-healing loop: a Routine periodically
    checks for open `scraper-blocked` issues and investigates/patches the
    scraper using the diagnostic snippet attached here.
    """
    title = f"Scraper blocked: {source}"
    body = (
        f"`{source}` has failed for several consecutive runs "
        "(bot detection or a broken selector/API pattern).\n\n"
        f"Diagnostic snippet from the most recent run:\n```\n{diagnostic[:2000]}\n```\n\n"
        "Needs a code fix in `concert-ticket-alerts/scrapers/` - update the "
        "network-capture URL pattern, stealth settings, or fallback logic."
    )
    existing = _find_open_issue(title)
    if existing:
        resp = requests.post(
            f"{_api_base()}/issues/{existing['number']}/comments",
            headers=_headers(),
            json={"body": f"Still blocked as of this run.\n\n{body}"},
            timeout=15,
        )
        resp.raise_for_status()
        logger.info("commented on existing issue #%s for %s", existing["number"], source)
    else:
        resp = requests.post(
            f"{_api_base()}/issues",
            headers=_headers(),
            json={"title": title, "body": body, "labels": [LABEL]},
            timeout=15,
        )
        resp.raise_for_status()
        logger.warning("opened a new GitHub issue for %s", source)


def resolve(source):
    """Close the escalation issue once a source is reporting healthy data again."""
    title = f"Scraper blocked: {source}"
    existing = _find_open_issue(title)
    if not existing:
        return
    resp = requests.patch(
        f"{_api_base()}/issues/{existing['number']}",
        headers=_headers(),
        json={"state": "closed"},
        timeout=15,
    )
    resp.raise_for_status()
    resp = requests.post(
        f"{_api_base()}/issues/{existing['number']}/comments",
        headers=_headers(),
        json={"body": f"`{source}` is reporting healthy data again - closing."},
        timeout=15,
    )
    resp.raise_for_status()
    logger.info("closed issue #%s for %s", existing["number"], source)
