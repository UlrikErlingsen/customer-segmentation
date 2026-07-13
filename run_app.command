#!/bin/bash
set -e

cd "$(dirname "$0")"

PID_FILE=".venv/.segmentsignal.pid"
PORT_FILE=".venv/.segmentsignal.port"

# A second double-click should reopen the running app, not fail on a port conflict.
if [ -f "$PID_FILE" ] && [ -f "$PORT_FILE" ]; then
  EXISTING_PID="$(/bin/cat "$PID_FILE")"
  EXISTING_PORT="$(/bin/cat "$PORT_FILE")"
  EXISTING_URL="http://127.0.0.1:${EXISTING_PORT}"
  if /bin/kill -0 "$EXISTING_PID" 2>/dev/null && /usr/bin/curl -fsS "${EXISTING_URL}/_stcore/health" >/dev/null 2>&1; then
    echo "SegmentSignal is already running. Opening it now."
    if [ "${SEGMENTSIGNAL_NO_BROWSER:-0}" != "1" ]; then
      /usr/bin/open "$EXISTING_URL"
    fi
    exit 0
  fi
  /bin/rm -f "$PID_FILE" "$PORT_FILE"
fi

if ! /usr/bin/env python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  echo "SegmentSignal needs Python 3.10 or newer."
  echo "Install it from https://www.python.org/downloads/ and try again."
  read -r -p "Press Return to close..."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Creating SegmentSignal's private Python environment..."
  /usr/bin/env python3 -m venv .venv
fi

source .venv/bin/activate

REQUIREMENTS_HASH="$(/usr/bin/shasum -a 256 requirements.txt | /usr/bin/awk '{print $1}')"
READY_FILE=".venv/.segmentsignal-requirements-${REQUIREMENTS_HASH}"
if [ ! -f "$READY_FILE" ]; then
  echo "First launch: downloading the app's Python packages. This can take a few minutes."
  echo "Later launches will be much faster and can work offline."
  python -m pip --disable-pip-version-check install --prefer-binary -r requirements.txt
  /bin/rm -f .venv/.segmentsignal-requirements-* .venv/.segmentsignal-ready
  /usr/bin/touch "$READY_FILE"
else
  echo "Using the existing SegmentSignal environment."
fi

if [ -n "${SEGMENTSIGNAL_PORT:-}" ]; then
  PORT="$SEGMENTSIGNAL_PORT"
else
  PORT="$(python - <<'PY'
import socket

for candidate in range(8501, 8600):
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", candidate))
    except OSError:
        continue
    finally:
        sock.close()
    print(candidate)
    break
else:
    raise SystemExit("No free local port was found between 8501 and 8599.")
PY
)"
fi

URL="http://127.0.0.1:${PORT}"
MAX_UPLOAD_MB="${SEGMENTSIGNAL_MAX_UPLOAD_MB:-200}"

echo "Starting SegmentSignal at ${URL}..."
python -m streamlit run app.py \
  --server.headless=true \
  --server.address=127.0.0.1 \
  --server.port="$PORT" \
  --server.maxUploadSize="$MAX_UPLOAD_MB" \
  --server.fileWatcherType=none \
  --browser.gatherUsageStats=false &
APP_PID=$!

echo "$APP_PID" > "$PID_FILE"
echo "$PORT" > "$PORT_FILE"

cleanup() {
  /bin/rm -f "$PID_FILE" "$PORT_FILE"
  if /bin/kill -0 "$APP_PID" 2>/dev/null; then
    /bin/kill "$APP_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

ATTEMPT=1
while [ "$ATTEMPT" -le 120 ]; do
  if /usr/bin/curl -fsS "${URL}/_stcore/health" >/dev/null 2>&1; then
    echo "SegmentSignal is ready. Opening your browser..."
    if [ "${SEGMENTSIGNAL_NO_BROWSER:-0}" != "1" ]; then
      /usr/bin/open "$URL"
    fi
    wait "$APP_PID"
    exit $?
  fi
  if ! /bin/kill -0 "$APP_PID" 2>/dev/null; then
    echo "SegmentSignal stopped before it became ready. Review the message above."
    wait "$APP_PID"
    exit $?
  fi
  ATTEMPT=$((ATTEMPT + 1))
  /bin/sleep 0.25
done

echo "SegmentSignal took too long to start. Review the message above, then try again."
exit 1
