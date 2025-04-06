#!/bin/bash
# Script to restart the WebSocket server with TTS feedback

# Project paths
BYTERACER_PATH="/home/pi/ByteRacer"
TTS_SCRIPT="${BYTERACER_PATH}/byteracer/tts/speak.py"
SCRIPTS_DIR="$(dirname "$0")"
LOG_FILE="${SCRIPTS_DIR}/restart_websocket.log"

exec > >(tee -a "${LOG_FILE}") 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ========== RESTART WEBSOCKET STARTED =========="

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

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

speak() {
    if [ -f "$TTS_SCRIPT" ]; then
        python3 "$TTS_SCRIPT" "$1"
    else
        log "TTS script not found: $TTS_SCRIPT"
    fi
}

log "Restarting WebSocket server (eaglecontrol)..."
speak "Restarting WebSocket service. Please wait."

SESSION_INFO=$(sudo -u pi screen -list | grep eaglecontrol)
if echo "$SESSION_INFO" | grep -q "(Dead"; then
    log "Screen session 'eaglecontrol' is dead. Wiping dead sessions and creating a new one..."
    run_cmd "sudo -u pi screen -wipe"
    run_cmd "sudo -u pi screen -dmS eaglecontrol bash -c 'cd ${BYTERACER_PATH}/eaglecontrol && bun run start; exec bash'"
else
    if [ -n "$SESSION_INFO" ]; then
        log "Screen session 'eaglecontrol' is active. Sending SIGINT for graceful shutdown..."
        run_cmd "sudo -u pi screen -S eaglecontrol -p 0 -X stuff \$'\003'"
        sleep 5

        PID=$(ps aux | grep "bun run start" | grep "eaglecontrol" | grep -v grep | awk '{print $2}' | head -n 1)
        if [ -n "$PID" ]; then
            log "WebSocket process did not exit gracefully, force killing PID $PID..."
            run_cmd "kill -9 $PID"
            sleep 2
        else
            log "WebSocket process exited gracefully."
        fi

        log "Restarting WebSocket server in existing screen session..."
        run_cmd "sudo -u pi screen -S eaglecontrol -p 0 -X stuff \"cd ${BYTERACER_PATH}/eaglecontrol && bun run start$(printf '\\r')\""
    else
        log "Screen session 'eaglecontrol' not found. Creating a new session..."
        run_cmd "sudo -u pi screen -dmS eaglecontrol bash -c 'cd ${BYTERACER_PATH}/eaglecontrol && bun run start; exec bash'"
    fi
fi

log "Waiting for process to start..."
sleep 5

PID=$(ps aux | grep "bun run start" | grep "eaglecontrol" | grep -v grep | awk '{print $2}' | head -n 1)
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
