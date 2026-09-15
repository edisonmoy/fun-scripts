"""Vercel Cron entry point: one snipe pass per invocation.

Vercel functions are stateless and start cold, so this relies on the
double-booking guard in sniper.has_existing_reservation() rather than on
any local state.

The endpoint is protected by CRON_SECRET. Without that check the function
URL is public, and anyone who found it could trigger a real booking
against your Resy account.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

# Vercel invokes this file directly; the shared modules live one level up.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import runner  # noqa: E402


def _authorized(headers):
    secret = os.environ.get("CRON_SECRET")
    if not secret:
        # Fail closed: an unset secret would otherwise leave booking
        # exposed on a public URL.
        return False
    return headers.get("Authorization") == f"Bearer {secret}"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not _authorized(self.headers):
            self._respond(401, {"error": "unauthorized (missing or bad CRON_SECRET)"})
            return

        try:
            outcomes = runner.run_once()
        except Exception as exc:
            self._respond(500, {"error": str(exc)})
            return

        self._respond(
            200,
            {
                "results": [
                    {
                        "target": o.target.key,
                        "status": o.status,
                        "day": o.day,
                        "time": o.slot.time_str if o.slot else None,
                        "reason": o.reason,
                    }
                    for o in outcomes
                ]
            },
        )

    def _respond(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
