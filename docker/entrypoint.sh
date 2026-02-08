#!/usr/bin/env bash
set -euo pipefail

if [ -d /workspace/InnoFranceVoiceGenerateAgent ]; then
  python3 -m pip install -e /workspace/InnoFranceVoiceGenerateAgent
fi

if [ -d /workspace/Kimi-Audio ]; then
  python3 -m pip install -e /workspace/Kimi-Audio
fi

if [ ! -d /workspace/InnoFranceApp/frontend/node_modules ]; then
  (cd /workspace/InnoFranceApp/frontend && npm install)
fi

BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
FRONTEND_PORT="${FRONTEND_PORT:-8003}"

cd /workspace/InnoFranceApp
python3 -m inno_france_app.server --host "$BACKEND_HOST" --port "$BACKEND_PORT" &
BACKEND_PID=$!

cd /workspace/InnoFranceApp/frontend
npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" &
FRONTEND_PID=$!

trap 'kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true' SIGINT SIGTERM
wait -n "$BACKEND_PID" "$FRONTEND_PID"
EXIT_CODE=$?
kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
exit "$EXIT_CODE"
