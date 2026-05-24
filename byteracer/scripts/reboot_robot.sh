#!/bin/bash

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export BYTERACER_PATH="${BYTERACER_PATH:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

LOG_FILE="${BYTERACER_LOG_DIR}/reboot_robot.log"
setup_logging "${LOG_FILE}"

log "========== REBOOT ROBOT STARTED =========="
speak_key "admin.reboot"

# Run the reboot inline rather than detaching a background child. This script
# is launched in its own systemd transient unit; a backgrounded grandchild
# would be killed when the unit's main process exits (KillMode=control-group)
# before it could trigger the reboot. A short sleep lets the TTS finish.
sleep 2

if systemd_available; then
    log "Rebooting through systemd"
    run_root systemctl reboot || {
        log "systemctl reboot failed"
        exit 1
    }
else
    log "Rebooting through reboot command"
    run_root reboot || {
        log "reboot command failed"
        exit 1
    }
fi

log "Reboot requested"
log "========== REBOOT ROBOT COMPLETED =========="
