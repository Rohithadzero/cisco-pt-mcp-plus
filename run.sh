#!/usr/bin/env sh
# Start ptgateway (Linux/macOS). Uses .venv if present, else python3.
cd "$(dirname "$0")"
PY=./.venv/bin/python; [ -x "$PY" ] || PY=python3
exec "$PY" -m ptgateway "$@"
