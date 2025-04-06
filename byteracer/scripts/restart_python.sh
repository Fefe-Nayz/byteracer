#!/bin/bash
# Script to restart the Python controller with TTS feedback

# Project paths
BYTERACER_PATH="/home/pi/ByteRacer"
TTS_SCRIPT="${BYTERACER_PATH}/byteracer/tts/speak.py"
SCRIPTS_DIR="$(dirname "$0")"
LOG_FILE="${SCRIPTS_DIR}/restart_python.log"

# Setup logging
exec > >(tee -a "${LOG_FILE}") 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ========== RESTART PYTHON STARTED =========="

# Log function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Run command and log its output
run_cmd() {
    local cmd="$1"
    log "Executing: $cmd"
    output=$(eval "$cmd" 2>&1)
    exit_code=$?
    if [ -n "$output" ]; then
        echo "$output" | while IFS= read -r line; do
            log "  > $line"
        done
    fi
    log "Command exit code: $exit_code"
    return $exit_code
}

# TTS function
speak() {
    if [ -f "$TTS_SCRIPT" ]; then
        python3 "$TTS_SCRIPT" "$1"
    else
        log "TTS script not found: $TTS_SCRIPT"
    fi
}

log "Restarting Python controller..."
speak "Restarting robot controller."

# Check the status of the 'byteracer' screen session (run as default user)
SESSION_INFO=$(sudo -u pi screen -list | grep byteracer)
if echo "$SESSION_INFO" | grep -q "(Dead"; then
    log "Screen session 'byteracer' is dead. Wiping dead sessions and creating a new one..."
    run_cmd "sudo -u pi screen -wipe"
    run_cmd "sudo -u pi screen -dmS byteracer bash -c 'cd ${BYTERACER_PATH}/byteracer && sudo python3 main.py; exec bash'"
else
    if [ -n "$SESSION_INFO" ]; then
        log "Screen session 'byteracer' is active. Sending SIGINT for graceful shutdown..."
        run_cmd "sudo -u pi screen -S byteracer -p 0 -X stuff \$'\003'"
        sleep 5  # Allow time for graceful shutdown

        PID=$(pgrep -f "python3 main.py" || echo "")
        if [ -n "$PID" ]; then
            log "Python process did not exit gracefully after SIGINT, force killing PID $PID..."
            run_cmd "kill -9 $PID"
            sleep 2
        else
            log "Python process exited gracefully."
        fi

        log "Restarting Python controller in existing screen session..."
        run_cmd "sudo -u pi screen -S byteracer -p 0 -X stuff \"cd ${BYTERACER_PATH}/byteracer && sudo python3 main.py$(printf '\\r')\""
    else
        log "Screen session 'byteracer' not found. Creating a new session..."
        run_cmd "sudo -u pi screen -dmS byteracer bash -c 'cd ${BYTERACER_PATH}/byteracer && sudo python3 main.py; exec bash'"
    fi
fi

log "Waiting for process to start..."
sleep 3

PID=$(pgrep -f "python3 main.py" || echo "")
if [ -n "$PID" ]; then
    log "Python controller has been restarted successfully with PID $PID."
    run_cmd "ps -p $PID -o pid,cmd,etime"
    speak "Robot controller has been restarted successfully."
else
    log "Error: Failed to restart Python controller!"
    run_cmd "ps aux | grep 'python3 main.py' | grep -v grep"
    speak "Failed to restart robot controller. Please check the system logs."
    exit 1
fi

log "========== RESTART PYTHON COMPLETED =========="
