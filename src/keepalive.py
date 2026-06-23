"""Keep-alive ping for Render free plan — prevents 30-60s cold starts.

Configure as a Render Cron Job:
  Command:  python -m src.keepalive
  Schedule: */10 * * * *
  Env vars: BACKEND_URL (e.g. https://analyseur-linkedin-influenceur-api.onrender.com)
"""
import os
import sys
import urllib.request

backend_url = os.environ.get("BACKEND_URL", "http://localhost:8000")
url = f"{backend_url}/health"

try:
    with urllib.request.urlopen(url, timeout=30) as resp:
        body = resp.read().decode()[:120]
        print(f"keep-alive OK ({resp.status}): {body}")
except Exception as exc:
    print(f"keep-alive FAILED: {exc}", file=sys.stderr)
    sys.exit(1)
