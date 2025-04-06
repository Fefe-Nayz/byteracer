#!/bin/bash
# Script to restart the WebSocket server with TTS feedback

# Project paths
BYTERACER_PATH="/home/pi/ByteRacer"
TTS_SCRIPT="${BYTERACER_PATH}/byteracer/tts/speak.py"
SCRIPTS_DIR="$(dirname "$0")"
LOG_FILE="${SCRIPTS_DIR}/restart_websocket.log"

# Setup logging
exec > >(tee -a "${LOG_FILE}") 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ========== RESTART WEBSOCKET STARTED =========="

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

log "Restarting WebSocket server (eaglecontrol)..."
speak "Restarting WebSocket service. Please wait."

if screen -list | grep -q "eaglecontrol"; then
    log "Screen session 'eaglecontrol' found. Sending SIGINT for graceful shutdown..."
    run_cmd "screen -S eaglecontrol -p 0 -X stuff \$'\003'"
    sleep 5  # Allow time for graceful shutdown

    PID=$(pgrep -f "bun run .* eaglecontrol" || echo "")
    if [ -n "$PID" ]; then
         log "WebSocket process did not exit gracefully, force killing PID $PID..."
         run_cmd "kill -9 $PID"
         sleep 2
    else
         log "WebSocket process exited gracefully."
    fi

    log "Restarting WebSocket server in existing screen session..."
    run_cmd "screen -S eaglecontrol -p 0 -X stuff \"cd ${BYTERACER_PATH}/eaglecontrol && bun run start$(printf '\\r')\""
else
    log "Screen session 'eaglecontrol' not found. Creating new eaglecontrol screen session..."
    run_cmd "screen -dmS eaglecontrol bash -c \"cd ${BYTERACER_PATH}/eaglecontrol && bun run start; exec bash\""
fi

log "Waiting for process to start..."
sleep 3

PID=$(pgrep -f "bun run .* eaglecontrol" || echo "")
if [ -n "$PID" ]; then
    log "WebSocket server has been restarted successfully with PID $PID."
    run_cmd "ps -p $PID -o pid,cmd,etime"
    speak "WebSocket server has been restarted successfully."
else
    log "Error: Failed to restart WebSocket server!"
    run_cmd "ps aux | grep 'bun run' | grep 'eaglecontrol' | grep -v grep"
    speak "Failed to restart WebSocket server. Please check the system logs."
    exit 1
fi

log "========== RESTART WEBSOCKET COMPLETED =========="
