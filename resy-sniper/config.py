import os

# Global default for whether target booking calls actually commit. Each
# target in targets.json can override this individually via its "dry_run"
# field (e.g. to test-run a newly added target while others stay live);
# targets that leave it unset fall back to this. Search/details calls
# always run live (they're read-only) regardless of this setting.
DRY_RUN = os.environ.get("RESY_DRY_RUN", "true").lower() != "false"

# Payment method to book with, as a Resy payment_methods[].id, shared
# across every target (one Resy account, one saved card). Optional - if
# unset, main.py resolves the account's default card once at startup via
# resy_api.get_default_payment_method_id(). Needed for any venue that
# requires a deposit/card-on-file - booking with no card (the fallback
# when neither this nor a default card is found) 402s on those.
PAYMENT_METHOD_ID = os.environ.get("RESY_PAYMENT_METHOD_ID")

# Poll cadence for one full round over every active target combined - not
# per target. More targets means a slower per-target check-in at the same
# total request rate against Resy, which is the point: total traffic stays
# bounded regardless of how many reservations you're watching at once.
POLL_INTERVAL_SECONDS = float(os.environ.get("RESY_POLL_INTERVAL_SECONDS", 2))
POLL_JITTER_SECONDS = float(os.environ.get("RESY_POLL_JITTER_SECONDS", 0.5))

AUTH_TOKEN = os.environ.get("RESY_AUTH_TOKEN")
API_KEY = os.environ.get("RESY_API_KEY")

# Fine-grained GitHub PAT scoped to just this repo, Contents: read/write.
# Used by github_sync.py to record a booking back into targets.json once
# a target books, so status survives a redeploy and the management webapp
# can display it.
GITHUB_TOKEN = os.environ.get("RESY_GITHUB_TOKEN")
