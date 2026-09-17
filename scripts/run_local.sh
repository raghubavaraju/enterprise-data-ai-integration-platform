#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Start the whole platform without Docker.  Useful when you want to attach a
# debugger, or when Docker is not available.
#
#   ./scripts/run_local.sh            start everything
#   ./scripts/run_local.sh stop       stop everything
#
# Logs go to .run/<service>.log, pids to .run/<service>.pid
# -----------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD:$PWD/services"
RUN_DIR=".run"
mkdir -p "$RUN_DIR"

stop_all() {
  for pidfile in "$RUN_DIR"/*.pid; do
    [ -e "$pidfile" ] || continue
    pid=$(cat "$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      # Wait for the port to be released before starting a replacement,
      # otherwise the new process fails to bind and dies silently.
      for _ in $(seq 1 40); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.1
      done
      kill -9 "$pid" 2>/dev/null || true
      echo "stopped $(basename "$pidfile" .pid) (pid $pid)"
    fi
    rm -f "$pidfile"
  done
}

start() {   # name module:app port [extra env assignments...]
  local name=$1 target=$2 port=$3; shift 3
  env "$@" python -m uvicorn "$target" --host 127.0.0.1 --port "$port" \
      > "$RUN_DIR/$name.log" 2>&1 &
  echo $! > "$RUN_DIR/$name.pid"
  printf '  %-22s http://127.0.0.1:%s\n' "$name" "$port"
}

if [ "${1:-start}" = "stop" ]; then stop_all; exit 0; fi

stop_all
echo "Building the local warehouse..."
WAREHOUSE_ACCESS=direct python -m local_warehouse.build >/dev/null

echo "Starting services:"
start crm                mock_services.crm.app:app      8081
start orders             mock_services.orders.app:app   8082
start support            mock_services.support.app:app  8083
start loyalty            mock_services.loyalty.app:app  8084
start catalog            mock_services.catalog.app:app  8085
start snowflake-data-api data_api.app:app               8092 WAREHOUSE_ACCESS=direct
start ai-service         ai_service.app:app             8087 WAREHOUSE_ACCESS=api
start system-api         gateway.main:app               8090 GATEWAY_LAYER=system
start process-api        gateway.main:app               8091 GATEWAY_LAYER=process
start experience-api     gateway.main:app               8080 GATEWAY_LAYER=experience
start store-experience-api gateway.main:app             8093 GATEWAY_LAYER=store-experience

echo
echo "Waiting for health checks..."
for port in 8081 8082 8083 8084 8085 8092 8087 8090 8091 8080 8093; do
  for _ in $(seq 1 40); do
    if curl -sf "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
      printf '  :%s UP\n' "$port"; break
    fi
    sleep 0.25
  done
done
echo
echo "Try it:  ./scripts/smoke_test.sh"
echo "Stop it: ./scripts/run_local.sh stop"
