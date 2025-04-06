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

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Function to run a command and log its output
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

# Function to speak with TTS
speak() {
    if [ -f "$TTS_SCRIPT" ]; then
        python3 "$TTS_SCRIPT" "$1"
    else
        log "TTS script not found: $TTS_SCRIPT"
    fi
}

log "Restarting Python controller..."
speak "Restarting robot controller."

# First, check if an active (non-dead) 'byteracer' screen session exists.
SESSION_ACTIVE=$(sudo -u pi screen -list | grep -v "Dead" | grep byteracer)

if [ -n "$SESSION_ACTIVE" ]; then
    log "Active screen session 'byteracer' found. Sending SIGINT for graceful shutdown..."
    run_cmd "sudo -u pi screen -S byteracer -p 0 -X stuff \$'\003'"
    sleep 5  # Wait for graceful shutdown

    PID=$(pgrep -f "python3 main.py" || echo "")
    if [ -n "$PID" ]; then
        log "Python process did not exit gracefully after SIGINT, force killing PID $PID..."
        run_cmd "kill -9 $PID"
        sleep 2
    else
        log "Python process exited gracefully."
    fi
else
    log "No active screen session 'byteracer' found."
fi

# Re-check for an active session after waiting
SESSION_ACTIVE=$(sudo -u pi screen -list | grep -v "Dead" | grep byteracer)
if [ -z "$SESSION_ACTIVE" ]; then
    log "No active session for 'byteracer' found. Creating a new screen session..."
    run_cmd "sudo -u pi screen -dmS byteracer bash -c 'cd ${BYTERACER_PATH}/byteracer && sudo python3 main.py; exec bash'"
else
    log "Active session found. Injecting restart command into 'byteracer'..."
    run_cmd "sudo -u pi screen -S byteracer -p 0 -X stuff \"cd ${BYTERACER_PATH}/byteracer && sudo python3 main.py$(printf '\\r')\""
fi

log "Waiting for process to start..."
sleep 3

PID=$(pgrep -f "python3 main.py" || echo "")
if [ -n "$PID" ]; then
    log "Python controller restarted successfully with PID $PID."
    run_cmd "ps -p $PID -o pid,cmd,etime"
    speak "Robot controller has been restarted successfully."
else
    log "Error: Failed to restart Python controller!"
    run_cmd "ps aux | grep 'python3 main.py' | grep -v grep"
    speak "Failed to restart robot controller. Please check the system logs."
    exit 1
fi

log "========== RESTART PYTHON COMPLETED =========="
