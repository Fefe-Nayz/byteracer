#!/bin/bash

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export BYTERACER_PATH="${BYTERACER_PATH:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

LOG_FILE="${BYTERACER_LOG_DIR}/restart_web_server.log"
setup_logging "${LOG_FILE}"

log "========== RESTART WEB SERVER STARTED =========="
speak "Restarting web server"

if [ ! -d "${BYTERACER_PATH}/relaytower/out" ]; then
    log "RelayTower build is missing; building before restart"
    build_relaytower_if_needed "true" || log "RelayTower build failed; attempting service start anyway"
fi

if systemd_unit_exists "byteracer-relaytower.service"; then
    if restart_systemd_unit "byteracer-relaytower.service" && wait_for_port "127.0.0.1" 3000 20; then
        log "Web server is listening on port 3000"
        speak "Web server restarted"
        log "========== RESTART WEB SERVER COMPLETED =========="
        exit 0
    fi
    log "Systemd restart failed; trying screen fallback"
fi

stop_screen_session "relaytower" "bun .*server.ts|next start"

if start_screen_session "relaytower" "${BYTERACER_PATH}/relaytower" "bun run start"; then
    if wait_for_port "127.0.0.1" 3000 30; then
        log "Web server is listening on port 3000"
        speak "Web server restarted"
    else
        log "RelayTower screen started but port 3000 is not ready"
        speak "Web server did not become ready"
        exit 1
    fi
else
    log "Failed to start RelayTower screen session"
    speak "Web server failed to start"
    exit 1
fi

log "========== RESTART WEB SERVER COMPLETED =========="
