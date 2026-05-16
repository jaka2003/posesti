#!/usr/bin/env bash
# One-shot setup za Ubuntu. Zazeni iz mape, kjer je monitor.py.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

echo "==> Preverjam python3..."
if ! command -v python3 >/dev/null; then
    echo "python3 ni najden. Instaliraj: sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
    exit 1
fi

echo "==> Ustvarjam venv..."
if [ ! -d venv ]; then
    python3 -m venv venv
fi

echo "==> Namescam pip pakete..."
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet curl_cffi beautifulsoup4

echo "==> Nastavljam izvrsljive pravice..."
chmod +x run.sh

echo "==> Preverjam .env..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo
    echo "!!! .env je bil skopiran iz .env.example. UREDI .env in nastavi NTFY_TOPIC."
    echo "    nano .env"
    echo
fi

echo "==> Probni zagon (prvi run pomni obstojece oglase, brez push)..."
./venv/bin/python monitor.py || true

echo
echo "==> Setup uspesen."
echo
echo "Cron postavi z:"
echo "    crontab -e"
echo "in dodaj vrstico:"
echo "    */20 * * * * $HERE/run.sh >> $HERE/run.log 2>&1"
echo
echo "Ali avtomatsko (pazi: doda na obstojeci crontab):"
echo "    (crontab -l 2>/dev/null; echo \"*/20 * * * * $HERE/run.sh >> $HERE/run.log 2>&1\") | crontab -"
