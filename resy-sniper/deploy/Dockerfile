# Fly.io worker: an always-on process polling on a short interval.
# Use this instead of Vercel Cron when you need to hit a venue's release
# time within seconds rather than within a minute.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

# --interval is the gap between full passes. Individual API calls are
# additionally throttled by RESY_MIN_REQUEST_INTERVAL.
CMD ["python", "cli.py", "watch", "--interval", "20"]
