#!/bin/bash
# Script to restart the Web server with TTS feedback

# Project paths
BYTERACER_PATH="/home/pi/ByteRacer"
TTS_SCRIPT="${BYTERACER_PATH}/byteracer/tts/speak.py"
SCRIPTS_DIR="$(dirname "$0")"
LOG_FILE="${SCRIPTS_DIR}/restart_web_server.log"

# Setup logging
exec > >(tee -a "${LOG_FILE}") 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ========== RESTART WEB SERVER STARTED =========="

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

log "Restarting Web server (relaytower)..."
speak "Restarting Web server. Please wait."

if sudo -u pi screen -list | grep -q "relaytower"; then
    log "Screen session 'relaytower' found. Sending SIGINT for graceful shutdown..."
    run_cmd "sudo -u pi screen -S relaytower -p 0 -X stuff \$'\003'"
    sleep 5  # Allow time for graceful shutdown

    PID=$(ps aux | grep "bun run start" | grep "relaytower" | grep -v grep | awk '{print $2}' | head -n 1)
    if [ -n "$PID" ]; then
         log "Web server process did not exit gracefully, force killing PID $PID..."
         run_cmd "kill -9 $PID"
         sleep 2
    else
         log "Web server process exited gracefully."
    fi

    log "Restarting Web server in existing screen session..."
    run_cmd "sudo -u pi screen -S relaytower -p 0 -X stuff \"cd ${BYTERACER_PATH}/relaytower && bun run start$(printf '\\r')\""
else
    log "Screen session 'relaytower' not found. Creating new relaytower screen session..."
    run_cmd "sudo -u pi screen -dmS relaytower bash -c \"cd ${BYTERACER_PATH}/relaytower && bun run start; exec bash\""
fi

log "Waiting for process to start..."
sleep 5

PID=$(ps aux | grep "bun run start" | grep "relaytower" | grep -v grep | awk '{print $2}' | head -n 1)
if [ -n "$PID" ]; then
    log "Web server has been restarted successfully with PID $PID."
    run_cmd "ps -p $PID -o pid,cmd,etime"
    speak "Web server has been restarted successfully."
else
    log "Error: Failed to restart Web server!"
    run_cmd "ps aux | grep 'bun run' | grep 'relaytower' | grep -v grep"
    speak "Failed to restart Web server. Please check the system logs."
    exit 1
fi

log "========== RESTART WEB SERVER COMPLETED =========="
