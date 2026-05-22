#!/bin/bash

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export BYTERACER_PATH="${BYTERACER_PATH:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

LOG_FILE="${BYTERACER_LOG_DIR}/restart_python.log"
setup_logging "${LOG_FILE}"

log "========== RESTART PYTHON STARTED =========="
speak "Redemarrage du controleur robot"

if systemd_unit_exists "byteracer-python.service"; then
    if restart_systemd_unit "byteracer-python.service"; then
        sleep 3
        if sudo systemctl is-active --quiet "byteracer-python.service"; then
            log "Python controller systemd service is active"
            speak "Controleur robot redemarre"
            log "========== RESTART PYTHON COMPLETED =========="
            exit 0
        fi
    fi
    log "Systemd restart failed; trying screen fallback"
fi

stop_screen_session "byteracer" "python[0-9.]* .*main.py|.venv/bin/python .*main.py"

PYTHON_BIN="$(byteracer_python)"
if start_screen_session "byteracer" "${BYTERACER_PATH}/byteracer" "sudo -E env PATH=${PATH} BYTERACER_PYTHON=${PYTHON_BIN} ${PYTHON_BIN} main.py"; then
    sleep 3
    if pgrep -f "python[0-9.]* .*main.py|.venv/bin/python .*main.py" >/dev/null 2>&1; then
        log "Python controller process is running"
        speak "Controleur robot redemarre"
    else
        log "Python screen started but controller process was not found"
        speak "Le controleur robot n'est pas pret"
        exit 1
    fi
else
    log "Failed to start Python screen session"
    speak "Echec du demarrage du controleur robot"
    exit 1
fi

log "========== RESTART PYTHON COMPLETED =========="
