#!/usr/bin/env bash
# The whole platform WITHOUT Docker: six services (each on its own throwaway SQLite file), an AWS emulator (moto) for the queue
# and the topic, the notification worker, and the React dev server. Same code, same API, same routes as AWS; only the database
# (SQLite instead of PostgreSQL) and the "cloud" (moto instead of SQS/SNS) are stand-ins. Use it when Docker is not available,
# or to check the business flows in about a minute.
#
#   scripts/e2e/native-stack.sh start      # prints the address to use: http://localhost:5173
#   scripts/e2e/native-stack.sh stop
#   scripts/e2e/native-stack.sh logs fee   # tail one component's log
#
# Admin login created for you:  admin@school.example  /  value of LOCAL_ADMIN_PASSWORD (default: native-stack-passphrase-1)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STATE="$ROOT/.e2e"
VENV="$ROOT/.venv-e2e"
PASSWORD="${LOCAL_ADMIN_PASSWORD:-native-stack-passphrase-1}"
SERVICES=(auth:8001 admission:8002 student:8003 fee:8004 attendance:8005 notification:8006)
mkdir -p "$STATE"

stop_all() {
  # On macOS the Python started by a virtual environment can hand over to a second process, so the recorded id is not always
  # the one that holds the port. Stop by port too, and the worker (which has no port) by its command line.
  for pidfile in "$STATE"/*.pid; do
    [[ -e "$pidfile" ]] || continue
    kill "$(cat "$pidfile")" 2>/dev/null || true
    rm -f "$pidfile"
  done
  for port in 5000 5173 8001 8002 8003 8004 8005 8006; do
    pids="$(lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null || true)"
    [[ -z "$pids" ]] || kill $pids 2>/dev/null || true
  done
  # The worker has no port; recognise it by its command line AND by running inside this repository's services folder.
  for pid in $(pgrep -f -- "-m app.worker" 2>/dev/null || true); do
    if lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | grep -q "^n$ROOT/services/"; then kill "$pid" 2>/dev/null || true; fi
  done
  for _ in $(seq 1 50); do   # wait until the ports are free: the old processes also hold the database files
    lsof -ti tcp:8001,8002,8003,8004,8005,8006,5000,5173 -sTCP:LISTEN >/dev/null 2>&1 || break
    sleep 0.2
  done
  echo "stopped"
}

wait_for() {  # wait_for <url> <name>
  for _ in $(seq 1 60); do curl -fsS "$1" >/dev/null 2>&1 && return 0; sleep 1; done
  echo "$2 did not become ready; see $STATE/$2.log" >&2; tail -20 "$STATE/$2.log" >&2 || true; exit 1
}

launch() {  # launch <name> <directory> <command...>   (environment is inherited)
  local name="$1" dir="$2"; shift 2
  ( cd "$dir" && nohup "$@" >"$STATE/$name.log" 2>&1 & echo $! >"$STATE/$name.pid" )
}

case "${1:-start}" in
  stop) stop_all; exit 0 ;;
  logs) tail -f "$STATE/${2:?component}.log"; exit 0 ;;
  start) ;;
  *) sed -n 2,13p "$0"; exit 1 ;;
esac

stop_all >/dev/null
rm -f "$STATE"/*.db

"$ROOT/scripts/gen-dev-keys.sh"
if [[ ! -x "$VENV/bin/python" ]]; then
  echo "creating the Python environment (once, a few minutes) ..."
  python3 -m venv "$VENV"
  args=(); for s in auth admission student fee attendance notification; do args+=(-r "$ROOT/services/$s/requirements-dev.txt"); done
  "$VENV/bin/pip" install -q --disable-pip-version-check "${args[@]}" "moto[server]==5.2.4"
fi
PY="$VENV/bin/python"

export AWS_ENDPOINT_URL="http://127.0.0.1:5000" AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_REGION=ap-south-1 AWS_DEFAULT_REGION=ap-south-1
export SQS_QUEUE_URL="http://127.0.0.1:5000/123456789012/school-events"
export SNS_TOPIC_ARN="arn:aws:sns:ap-south-1:123456789012:school-notifications"
export ENVIRONMENT=local AUTO_CREATE_TABLES=true LOG_LEVEL=INFO POLL_WAIT_SECONDS=2
export JWT_ISSUER=school-auth JWT_AUDIENCE=school-api
export STUDENT_SERVICE_URL="http://127.0.0.1:8003"

echo "starting the AWS emulator (queue, topic) ..."
launch moto "$ROOT" "$VENV/bin/moto_server" -p 5000
wait_for http://127.0.0.1:5000/moto-api/ moto
"$PY" "$ROOT/scripts/local_aws_init.py" >/dev/null

for entry in "${SERVICES[@]}"; do
  name="${entry%%:*}"; port="${entry##*:}"
  echo "starting $name on :$port ..."
  extra=()
  [[ "$name" == "auth" ]] && extra=(JWT_PRIVATE_KEY_FILE="$ROOT/.dev-keys/jwt_private.pem")
  ( export DATABASE_URL="sqlite:///$STATE/$name.db" JWT_PUBLIC_KEY_FILE="$ROOT/.dev-keys/jwt_public.pem" ${extra[@]+"${extra[@]}"}
    launch "$name" "$ROOT/services/$name" "$PY" -m uvicorn app.asgi:app --host 127.0.0.1 --port "$port" --no-access-log )
done
for entry in "${SERVICES[@]}"; do wait_for "http://127.0.0.1:${entry##*:}/health" "${entry%%:*}"; done

echo "starting the notification worker ..."
( export DATABASE_URL="sqlite:///$STATE/notification.db" JWT_PUBLIC_KEY_FILE="$ROOT/.dev-keys/jwt_public.pem"
  launch notification-worker "$ROOT/services/notification" "$PY" -m app.worker )

echo "creating the administrator ..."
( cd "$ROOT/services/auth" && DATABASE_URL="sqlite:///$STATE/auth.db" AUTH_ADMIN_PASSWORD="$PASSWORD" \
  JWT_PRIVATE_KEY_FILE="$ROOT/.dev-keys/jwt_private.pem" JWT_PUBLIC_KEY_FILE="$ROOT/.dev-keys/jwt_public.pem" \
  "$PY" -m app.cli create-admin --email admin@school.example --name "Local Admin" )

echo "starting the web portal ..."
( cd "$ROOT/frontend" && [[ -d node_modules ]] || npm ci --silent )
launch frontend "$ROOT/frontend" npm run dev -- --port 5173 --strictPort
wait_for http://127.0.0.1:5173/ frontend

echo
echo "Ready:  http://localhost:5173      login admin@school.example / $PASSWORD"
echo "Test:   SMOKE_EMAIL=admin@school.example SMOKE_PASSWORD='$PASSWORD' scripts/e2e/smoke.py http://localhost:5173"
echo "Stop:   scripts/e2e/native-stack.sh stop"
