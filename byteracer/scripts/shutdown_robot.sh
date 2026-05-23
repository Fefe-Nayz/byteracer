#!/bin/bash

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export BYTERACER_PATH="${BYTERACER_PATH:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

LOG_FILE="${BYTERACER_LOG_DIR}/shutdown_robot.log"
setup_logging "${LOG_FILE}"

log "========== SHUTDOWN ROBOT STARTED =========="
speak_key "admin.shutdown"

if systemd_available; then
    log "Scheduling poweroff through systemd"
    nohup bash -c 'sleep 2; exec sudo systemctl poweroff' >/dev/null 2>&1 &
else
    log "Scheduling shutdown command"
    nohup bash -c 'sleep 2; exec sudo shutdown -h now' >/dev/null 2>&1 &
fi

log "Shutdown scheduled"
log "========== SHUTDOWN ROBOT COMPLETED =========="
