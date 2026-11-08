#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python ]]; then
  if command -v python3.12 >/dev/null 2>&1; then
    python3.12 -m venv .venv
  else
    python3 -m venv .venv
  fi
fi

.venv/bin/python - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10 or newer is required. Use python3.12 to create .venv.")
PY

.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example. Edit DATABASE_URL in .env, then run ./start.sh again."
  exit 1
fi

exec .venv/bin/python -m incident_intelligence
