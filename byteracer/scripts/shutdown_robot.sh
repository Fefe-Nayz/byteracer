#!/bin/bash

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export BYTERACER_PATH="${BYTERACER_PATH:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

LOG_FILE="${BYTERACER_LOG_DIR}/shutdown_robot.log"
setup_logging "${LOG_FILE}"

log "========== SHUTDOWN ROBOT STARTED =========="
speak_key "admin.shutdown" --volume 100

# Let the controller announce the power-off one last time when systemd stops it,
# right before the machine actually shuts down (which is minutes after this point).
set_power_action "shutdown"

# Run the poweroff inline rather than detaching a background child. This script
# is launched in its own systemd transient unit; a backgrounded grandchild
# would be killed when the unit's main process exits (KillMode=control-group)
# before it could trigger the poweroff. speak_key blocks until playback completes,
# so the poweroff request is sent immediately after the audible warning.

if systemd_available; then
    log "Powering off through systemd"
    run_root systemctl poweroff || {
        log "systemctl poweroff failed"
        exit 1
    }
else
    log "Powering off through shutdown command"
    run_root shutdown -h now || {
        log "shutdown command failed"
        exit 1
    }
fi

log "Poweroff requested"
log "========== SHUTDOWN ROBOT COMPLETED =========="
