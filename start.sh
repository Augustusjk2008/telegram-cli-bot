#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export TELEGRAM_CLI_BRIDGE_SUPERVISOR=1
MODE="${1:-default}"

if [[ "$MODE" == "web" ]]; then
  export TELEGRAM_ENABLED="false"
  export WEB_ENABLED="true"
fi

while true; do
  python -m bot
  exit_code=$?
  if [[ "$exit_code" -ne 75 ]]; then
    exit "$exit_code"
  fi
  sleep 1
done
