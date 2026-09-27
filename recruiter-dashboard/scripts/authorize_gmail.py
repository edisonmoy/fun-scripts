"""One-time, manually-run script to obtain a Gmail OAuth refresh token.

The dashboard's sync and send routes use this token to read and reply to
Edison's Gmail. Run it locally, once, whenever setting up (or
re-authorizing) access.

Setup:
1. In Google Cloud Console, create an OAuth client of type "Desktop app"
   (APIs & Services -> Credentials), with the Gmail API enabled on the
   project.
2. Either download the client secret JSON next to this script as
   `client_secret.json`, or export GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET.
3. `pip install google-auth-oauthlib`, then run `python authorize_gmail.py`.
   It opens a browser for the OAuth consent flow (scopes: gmail.modify,
   gmail.compose, gmail.send) and prints a refresh token.
4. Set `GMAIL_REFRESH_TOKEN`, `GMAIL_CLIENT_ID` and `GMAIL_CLIENT_SECRET`
   as environment variables on the recruiter-dashboard Vercel project.

The printed refresh token is a long-lived credential - treat it like a
password (don't paste it into logs, commits, or chat).
"""

import json
import os

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
]


def _client_config():
    client_id = os.environ.get("GMAIL_CLIENT_ID")
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET")
    if client_id and client_secret:
        return {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }

    with open("client_secret.json") as f:
        return json.load(f)


def main():
    flow = InstalledAppFlow.from_client_config(_client_config(), SCOPES)
    credentials = flow.run_local_server(port=0)
    print("Success. Set this as GMAIL_REFRESH_TOKEN on the Vercel project:")
    print(credentials.refresh_token)


if __name__ == "__main__":
    main()
