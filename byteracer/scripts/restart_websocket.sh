#!/bin/bash

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export BYTERACER_PATH="${BYTERACER_PATH:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

LOG_FILE="${BYTERACER_LOG_DIR}/restart_websocket.log"
setup_logging "${LOG_FILE}"

log "========== RESTART WEBSOCKET STARTED =========="
speak "Restarting WebSocket service"

if systemd_unit_exists "byteracer-eaglecontrol.service"; then
    if restart_systemd_unit "byteracer-eaglecontrol.service" && wait_for_port "127.0.0.1" 3001 20; then
        log "WebSocket service is listening on port 3001"
        speak "WebSocket service restarted"
        log "========== RESTART WEBSOCKET COMPLETED =========="
        exit 0
    fi
    log "Systemd restart failed; trying screen fallback"
fi

stop_screen_session "eaglecontrol" "bun .*index.ts"

if start_screen_session "eaglecontrol" "${BYTERACER_PATH}/eaglecontrol" "bun run start"; then
    if wait_for_port "127.0.0.1" 3001 20; then
        log "WebSocket service is listening on port 3001"
        speak "WebSocket service restarted"
    else
        log "WebSocket screen started but port 3001 is not ready"
        speak "WebSocket service did not become ready"
        exit 1
    fi
else
    log "Failed to start WebSocket screen session"
    speak "WebSocket service failed to start"
    exit 1
fi

log "========== RESTART WEBSOCKET COMPLETED =========="
