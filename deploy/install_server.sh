#!/usr/bin/env bash
# Install or update the Brawl Arena server on Debian/Ubuntu. Run as root:
#   sudo bash deploy/install_server.sh            (or: PORT=5000 sudo -E bash ...)
# Safe to re-run: it pulls the latest code and restarts the service.
set -euo pipefail

REPO="${REPO:-https://github.com/Raphael-11/network2d-game.git}"
DIR=/opt/brawl-arena
PORT="${PORT:-5000}"

apt-get update -qq
apt-get install -y -qq git python3 >/dev/null

id brawl >/dev/null 2>&1 || useradd --system --home-dir "$DIR" --shell /usr/sbin/nologin brawl

if [ -d "$DIR/.git" ]; then
    runuser -u brawl -- git -C "$DIR" pull --ff-only
else
    git clone "$REPO" "$DIR"
    chown -R brawl:brawl "$DIR"
fi

echo "== running the test suite"
(cd "$DIR" && runuser -u brawl -- python3 test_core.py)

sed "s/--port 5000/--port $PORT/" "$DIR/deploy/brawl-arena.service" > /etc/systemd/system/brawl-arena.service
systemctl daemon-reload
systemctl enable brawl-arena >/dev/null
systemctl restart brawl-arena

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
    ufw allow "$PORT/tcp"
fi

sleep 1
systemctl --no-pager --lines=5 status brawl-arena || true
echo
echo "Brawl Arena server listening on TCP port $PORT."
echo "Players run:  play.bat <this server's public IP>   (Windows)"
echo "              ./play.sh <this server's public IP>  (Linux/macOS)"
