#!/bin/bash
# Script to restart all ByteRacer services with TTS feedback

# Project paths
BYTERACER_PATH="/home/pi/ByteRacer"
TTS_SCRIPT="${BYTERACER_PATH}/byteracer/tts/speak.py"
SCRIPTS_PATH="${BYTERACER_PATH}/byteracer/scripts"
SCRIPTS_DIR="$(dirname "$0")"
LOG_FILE="${SCRIPTS_DIR}/restart_services.log"

exec > >(tee -a "${LOG_FILE}") 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ========== RESTART ALL SERVICES STARTED =========="

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

# Make sure individual scripts are executable
run_cmd "chmod +x \"${SCRIPTS_PATH}/restart_websocket.sh\""
run_cmd "chmod +x \"${SCRIPTS_PATH}/restart_web_server.sh\""
run_cmd "chmod +x \"${SCRIPTS_PATH}/restart_python.sh\""

log "Restarting all ByteRacer services..."
speak "Restarting all ByteRacer services. This may take a moment."

log "Calling restart_websocket.sh"
run_cmd "\"${SCRIPTS_PATH}/restart_websocket.sh\""
WEBSOCKET_EXIT=$?
if [ $WEBSOCKET_EXIT -ne 0 ]; then
    log "Error: restart_websocket.sh failed with exit code $WEBSOCKET_EXIT"
fi

log "Calling restart_web_server.sh"
run_cmd "\"${SCRIPTS_PATH}/restart_web_server.sh\""
WEBSERVER_EXIT=$?
if [ $WEBSERVER_EXIT -ne 0 ]; then
    log "Error: restart_web_server.sh failed with exit code $WEBSERVER_EXIT"
fi

log "Calling restart_python.sh"
run_cmd "\"${SCRIPTS_PATH}/restart_python.sh\""
PYTHON_EXIT=$?
if [ $PYTHON_EXIT -ne 0 ]; then
    log "Error: restart_python.sh failed with exit code $PYTHON_EXIT"
fi

log "All services restart process completed."
speak "All services restart process completed."

session_exists() {
    sudo -u pi screen -list | grep -v "Dead" | grep -q "$1"
    return $?
}

all_running=true
for session in "eaglecontrol" "relaytower" "byteracer"; do
    if ! run_cmd "sudo -u pi screen -list" | grep -v "Dead" | grep -q "$session"; then
        log "Warning: $session is not running!"
        speak "Warning! $session is not running."
        all_running=false
    else
        log "Session $session is running."
    fi
done

log "Process status check:"
run_cmd "ps aux | grep -E 'python3 main.py|bun run .* eaglecontrol|bun run .* relaytower' | grep -v grep"

log "Screen sessions:"
run_cmd "sudo -u pi screen -list"

if [ "$all_running" = true ]; then
    log "All services are now running correctly."
    speak "All services are now running correctly."
else
    log "Some services failed to restart. Please check the logs."
    speak "Warning! Some services failed to restart. Please check the logs."
fi

log "========== RESTART ALL SERVICES COMPLETED =========="
