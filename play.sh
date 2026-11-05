#!/usr/bin/env sh
# Brawl Arena launcher for Linux/macOS.  Usage:  ./play.sh SERVER_IP [PORT]
set -e
cd "$(dirname "$0")"
SERVER="${1:-}"
PORT="${2:-5000}"
if [ -z "$SERVER" ]; then
    printf "Server IP or hostname: "
    read -r SERVER
fi
PY="${PYTHON:-python3}"
if ! "$PY" -c "import pygame" >/dev/null 2>&1; then
    echo "Installing pygame ..."
    "$PY" -m pip install --user -r requirements.txt
fi
exec "$PY" -m client.run_client --transport tcp --host "$SERVER" --port "$PORT"
