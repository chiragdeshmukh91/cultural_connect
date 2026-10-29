#!/usr/bin/env bash
# Culture Connect - local run (macOS/Linux/WSL)
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
python scripts/qloo_smoke_test.py || true
echo "Open http://localhost:8000"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
