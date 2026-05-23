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

# Run the poweroff inline rather than detaching a background child. This script
# is launched in its own systemd transient unit; a backgrounded grandchild
# would be killed when the unit's main process exits (KillMode=control-group)
# before it could trigger the poweroff. A short sleep lets the TTS finish.
sleep 2

if systemd_available; then
    log "Powering off through systemd"
    sudo systemctl poweroff
else
    log "Powering off through shutdown command"
    sudo shutdown -h now
fi

log "Poweroff requested"
log "========== SHUTDOWN ROBOT COMPLETED =========="
