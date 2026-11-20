#!/usr/bin/env bash
# Run the offline GCS locally on macOS or Linux.
set -euo pipefail
cd "$(dirname "$0")/.."
root="$PWD"
python="${PYTHON:-python3}"
if ! command -v "$python" >/dev/null || ! "$python" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
  echo 'Python 3.11+ is required (macOS: brew install python).' >&2
  exit 1
fi
if ! command -v npm >/dev/null || ! command -v node >/dev/null || ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) < 20 ? 1 : 0)'; then
  echo 'Node.js 20+ and npm are required (macOS: brew install node).' >&2
  exit 1
fi
if [[ "${1:-}" == "--setup" ]]; then
  "$python" -m venv backend/.venv
  backend/.venv/bin/python -m pip install -r backend/requirements.txt
  (cd frontend && npm install --no-package-lock)
  shift
fi
if [[ $# -ne 0 ]]; then
  echo 'Usage: ./scripts/run-nidar.sh [--setup]' >&2
  exit 2
fi
if [[ ! -x backend/.venv/bin/python || ! -x frontend/node_modules/.bin/vite ]]; then
  echo 'Run ./scripts/run-nidar.sh --setup first.' >&2
  exit 1
fi
if [[ -z "${NIDAR_BRIDGE_TOKEN:-}" ]]; then
  echo 'NIDAR_BRIDGE_TOKEN is unset: console can open, but onboard publishing is disabled.' >&2
fi
backend_pid=''
frontend_pid=''
cleanup() {
  if [[ -n "$frontend_pid" ]]; then kill "$frontend_pid" 2>/dev/null || true; fi
  if [[ -n "$backend_pid" ]]; then kill "$backend_pid" 2>/dev/null || true; fi
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
(cd backend && exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000) &
backend_pid=$!
(cd frontend && exec "$root/frontend/node_modules/.bin/vite" --host 127.0.0.1 --port 5173 --strictPort) &
frontend_pid=$!
printf '\nNIDAR console: http://127.0.0.1:5173/nidar (Ctrl+C to stop)\n\n'
# macOS ships Bash 3.2, which does not support wait -n.
while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do
  sleep 1
done
if ! kill -0 "$backend_pid" 2>/dev/null; then wait "$backend_pid"; else wait "$frontend_pid"; fi
