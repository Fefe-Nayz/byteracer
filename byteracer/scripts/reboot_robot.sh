#!/bin/bash

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export BYTERACER_PATH="${BYTERACER_PATH:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

LOG_FILE="${BYTERACER_LOG_DIR}/reboot_robot.log"
setup_logging "${LOG_FILE}"

log "========== REBOOT ROBOT STARTED =========="
speak "Redemarrage du robot"

if systemd_available; then
    log "Scheduling reboot through systemd"
    nohup bash -c 'sleep 2; exec sudo systemctl reboot' >/dev/null 2>&1 &
else
    log "Scheduling reboot through reboot command"
    nohup bash -c 'sleep 2; exec sudo reboot' >/dev/null 2>&1 &
fi

log "Reboot scheduled"
log "========== REBOOT ROBOT COMPLETED =========="
