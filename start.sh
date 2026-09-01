#!/usr/bin/env bash
# start.sh — launch the Reconciliation Console and expose it on the LAN.
#
# Usage:
#   ./start.sh           # defaults: port 8000, auto-detects LAN IP
#   PORT=9000 ./start.sh # use a different port

set -e

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
STATIC_IP="${STATIC_IP:-192.168.1.2}"
APP_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$APP_DIR/venv" ]; then
    python -m venv "$APP_DIR/venv"
fi
# Activate venv if it exists next to this script
if [ -f "$APP_DIR/venv/bin/activate" ]; then
    source "$APP_DIR/venv/bin/activate"
fi

if [ ! -f "$APP_DIR/requirements.txt" ]; then
    pip install -r "$APP_DIR/requirements.txt"
fi


echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Reconciliation Console"
echo "  Local:   http://localhost:${PORT}"
echo "  Network: http://${STATIC_IP}:${PORT}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

cd "$APP_DIR"
# Dev/test mode: operate only on the generated test DB under data/test_<scenario>/test.db
SCENARIO="${SCENARIO:-1.1}"
TEST_DB_PATH="$APP_DIR/data/test_${SCENARIO//./_}/test.db"

if [ -f "$TEST_DB_PATH" ]; then
    export COMMISSIONS_DB="$TEST_DB_PATH"
    echo "Found test DB at $COMMISSIONS_DB — starting in dev mode."
else
    echo "No test DB found at $TEST_DB_PATH."
    read -r -p "Create a development test DB and dev user for scenario ${SCENARIO}? [Y/n] " yn
    yn="${yn:-Y}"
    if [[ "$yn" =~ ^[Yy] ]]; then
        echo "Creating test DB (scenario $SCENARIO)..."
        # run the bundled test DB generator; it prints the dev credentials
        python "$APP_DIR/tests/test file generator/generate_test_data.py" --scenario "$SCENARIO"
        export COMMISSIONS_DB="$TEST_DB_PATH"
        echo "Created $COMMISSIONS_DB"
        echo "To run the app against this test DB, start the server with:"
        echo "  COMMISSIONS_DB=./data/test_${SCENARIO//./_} python backend/main.py"
    else
        echo "Proceeding without creating a test DB. The app will initialize a default admin on first run if no DB exists."
    fi
fi

# Launch uvicorn (keep in background so we can open a browser), then wait.
"$APP_DIR/venv/bin/uvicorn" backend.main:app --host "$HOST" --port "$PORT" &
UVICORN_PID=$!
sleep 1
LOCAL_URL="http://localhost:${PORT}"
echo "Server launched (pid $UVICORN_PID)."
if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$LOCAL_URL" || true
fi
echo "Open the app at: $LOCAL_URL"
wait "$UVICORN_PID"
