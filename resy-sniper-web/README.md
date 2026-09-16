# Resy sniper web

Small password-gated dashboard for managing `resy-sniper/targets.json` -
the list of reservations the [resy-sniper](../resy-sniper) bot is
watching. Deployed at resy.edisonmoy.com.

## How it works

There's no database - this reads and writes `resy-sniper/targets.json`
directly via the GitHub Contents API. Saving a change commits to `main`,
which triggers `.github/workflows/resy-sniper-deploy.yml` to redeploy the
bot on Fly.io (targets.json is baked into its Docker image, not fetched
at runtime) - so changes take about 1-2 minutes to go live after saving.

- `lib/github.ts` - fetch/commit `targets.json` via the GitHub API.
- `lib/auth.ts` + `middleware.ts` - single shared-password gate. The
  session cookie is an HMAC keyed by `AUTH_SECRET`, not the password
  itself.
- `app/page.tsx` - the dashboard: edit fields inline, add/remove targets,
  one "Save changes" button rewrites the whole file.
- `app/login/page.tsx` - password prompt.

## Local development

```bash
cd resy-sniper-web
npm install
cp .env.example .env.local   # fill in ADMIN_PASSWORD, AUTH_SECRET, GITHUB_TOKEN
npm run dev
```

## Environment variables

| Var | What |
| --- | --- |
| `ADMIN_PASSWORD` | Shared password to log in |
| `AUTH_SECRET` | Random string that signs the session cookie |
| `GITHUB_TOKEN` | Fine-grained PAT, scoped to `edisonmoy/fun-scripts`, Contents: read/write |

## Known limitations

- No live booking status (whether a target has actually booked yet) -
  that state lives in the bot's ephemeral `state.json` on Fly, not
  anywhere this app can read. Check `fly logs -a resy-sniper-snowy-field-9084`
  for that.
- Single shared password, no per-user accounts - fine for a personal tool,
  not meant to scale beyond that.
- Optimistic-concurrency only: if you have two browser tabs open and save
  from both, the second save fails with a stale-sha error from GitHub
  rather than silently overwriting - reload and reapply in that case.
