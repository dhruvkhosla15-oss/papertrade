#!/usr/bin/env bash
# Quick local run without Docker (simulated prices by default).
cd "$(dirname "$0")"
pip install -r requirements.txt -q
set -a; [ -f .env ] && . ./.env; set +a
export PT_FEED=${PT_FEED:-mock}
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
