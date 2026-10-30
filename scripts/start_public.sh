#!/usr/bin/env bash
# Start Culture Connect + a public Cloudflare quick-tunnel link in the background (WSL / Linux).
# Usage (from the project folder):  bash scripts/start_public.sh
set -e
cd "$(dirname "$0")/.."
VENV=.venv-wsl
[ -x "$VENV/bin/python" ] || { echo "Creating $VENV..."; python3 -m venv "$VENV"; "$VENV/bin/pip" install -q -r requirements.txt; }
if [ ! -x ./cloudflared ]; then
  echo "Downloading the Cloudflare tunnel tool..."
  if ! curl -fL --progress-bar -o cloudflared.tmp https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64; then
    rm -f cloudflared.tmp; echo "Could not download cloudflared (see the error above). Check your internet/proxy and run this script again."; exit 1
  fi
  mv cloudflared.tmp cloudflared; chmod +x cloudflared
fi
echo "Starting the app..."
pkill -f "uvicorn backend.main:app" 2>/dev/null || true
pkill -f "cloudflared tunnel" 2>/dev/null || true
nohup "$VENV/bin/python" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 > app.log 2>&1 &
for i in $(seq 1 30); do curl -sf http://127.0.0.1:8000/api/health >/dev/null && break; sleep 1; done
curl -sf http://127.0.0.1:8000/api/health >/dev/null || { echo "App did not start - see app.log"; tail -20 app.log; exit 1; }
echo "Opening the public link..."
nohup ./cloudflared tunnel --url http://localhost:8000 > tunnel.log 2>&1 &
for i in $(seq 1 30); do URL=$(grep -so 'https://[a-z0-9-]*\.trycloudflare\.com' tunnel.log | head -1); [ -n "$URL" ] && break; sleep 1; done
[ -n "$URL" ] || { echo "Tunnel did not start - see tunnel.log"; tail -20 tunnel.log; exit 1; }
echo "$URL" > public_url.txt
echo "App running. Public link: $URL"
