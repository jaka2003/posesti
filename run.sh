#!/usr/bin/env bash
# Launcher za cron. Zazene monitor.py v venv-u.
set -euo pipefail
cd "$(dirname "$0")"
./venv/bin/python monitor.py
