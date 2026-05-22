#!/bin/bash

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export BYTERACER_PATH="${BYTERACER_PATH:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

LOG_FILE="${BYTERACER_LOG_DIR}/restart_services.log"
setup_logging "${LOG_FILE}"

log "========== RESTART ALL SERVICES STARTED =========="
speak "Redemarrage des services ByteRacer"

chmod +x "${SCRIPT_DIR}/restart_websocket.sh" "${SCRIPT_DIR}/restart_web_server.sh" "${SCRIPT_DIR}/restart_python.sh" 2>/dev/null || true

WEBSOCKET_EXIT=0
WEBSERVER_EXIT=0
PYTHON_EXIT=0

"${SCRIPT_DIR}/restart_websocket.sh" || WEBSOCKET_EXIT=$?
"${SCRIPT_DIR}/restart_web_server.sh" || WEBSERVER_EXIT=$?
"${SCRIPT_DIR}/restart_python.sh" || PYTHON_EXIT=$?

log "Screen sessions after restart:"
screen_list

if [ "${WEBSOCKET_EXIT}" -eq 0 ] && [ "${WEBSERVER_EXIT}" -eq 0 ] && [ "${PYTHON_EXIT}" -eq 0 ]; then
    log "All services restarted successfully"
    speak "Services redemarres"
else
    log "Restart failures: websocket=${WEBSOCKET_EXIT}, web=${WEBSERVER_EXIT}, python=${PYTHON_EXIT}"
    speak "Echec du redemarrage de certains services"
    exit 1
fi

log "========== RESTART ALL SERVICES COMPLETED =========="
