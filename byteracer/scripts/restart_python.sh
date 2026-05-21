#!/bin/bash

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export BYTERACER_PATH="${BYTERACER_PATH:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

LOG_FILE="${BYTERACER_LOG_DIR}/restart_python.log"
setup_logging "${LOG_FILE}"

log "========== RESTART PYTHON STARTED =========="
speak "Restarting robot controller"

if systemd_unit_exists "byteracer-python.service"; then
    if restart_systemd_unit "byteracer-python.service"; then
        sleep 3
        if sudo systemctl is-active --quiet "byteracer-python.service"; then
            log "Python controller systemd service is active"
            speak "Robot controller restarted"
            log "========== RESTART PYTHON COMPLETED =========="
            exit 0
        fi
    fi
    log "Systemd restart failed; trying screen fallback"
fi

stop_screen_session "byteracer" "python3 .*main.py"

if start_screen_session "byteracer" "${BYTERACER_PATH}/byteracer" "sudo -E env PATH=${PATH} python3 main.py"; then
    sleep 3
    if pgrep -f "python3 .*main.py" >/dev/null 2>&1; then
        log "Python controller process is running"
        speak "Robot controller restarted"
    else
        log "Python screen started but controller process was not found"
        speak "Robot controller did not become ready"
        exit 1
    fi
else
    log "Failed to start Python screen session"
    speak "Robot controller failed to start"
    exit 1
fi

log "========== RESTART PYTHON COMPLETED =========="
