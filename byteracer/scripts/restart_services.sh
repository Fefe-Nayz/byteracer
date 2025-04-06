#!/bin/bash
# Script to restart all ByteRacer services with TTS feedback

# Project paths
BYTERACER_PATH="/home/pi/ByteRacer"
TTS_SCRIPT="${BYTERACER_PATH}/byteracer/tts/speak.py"
SCRIPTS_PATH="${BYTERACER_PATH}/byteracer/scripts"
SCRIPTS_DIR="$(dirname "$0")"
LOG_FILE="${SCRIPTS_DIR}/restart_services.log"

# Setup logging
exec > >(tee -a "${LOG_FILE}") 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ========== RESTART ALL SERVICES STARTED =========="

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Function to speak with TTS
speak() {
    if [ -f "$TTS_SCRIPT" ]; then
        python3 "$TTS_SCRIPT" "$1"
    else
        log "TTS script not found: $TTS_SCRIPT"
    fi
}

# Make sure all scripts are executable
chmod +x "${SCRIPTS_PATH}/restart_websocket.sh"
chmod +x "${SCRIPTS_PATH}/restart_web_server.sh"
chmod +x "${SCRIPTS_PATH}/restart_python.sh"

log "Restarting all ByteRacer services..."
speak "Restarting all ByteRacer services. This may take a moment."

# Restart WebSocket server (eaglecontrol)
log "Calling restart_websocket.sh"
"${SCRIPTS_PATH}/restart_websocket.sh"
if [ $? -ne 0 ]; then
    log "Error: restart_websocket.sh failed with exit code $?"
fi

# Restart Web server (relaytower)
log "Calling restart_web_server.sh"
"${SCRIPTS_PATH}/restart_web_server.sh"
if [ $? -ne 0 ]; then
    log "Error: restart_web_server.sh failed with exit code $?"
fi

# Restart Python controller (byteracer)
log "Calling restart_python.sh"
"${SCRIPTS_PATH}/restart_python.sh"
if [ $? -ne 0 ]; then
    log "Error: restart_python.sh failed with exit code $?"
fi

# Final message
log "All services restart process completed."
speak "All services restart process completed."

# Function to check if a screen session exists
session_exists() {
    screen -ls | grep -q "$1"
    return $?
}

# Verify all services are running
all_running=true
for session in "eaglecontrol" "relaytower" "byteracer"; do
    if ! session_exists "$session"; then
        log "Warning: $session is not running!"
        speak "Warning! $session is not running."
        all_running=false
    else
        log "Session $session is running."
    fi
done

if [ "$all_running" = true ]; then
    log "All services are now running correctly."
    speak "All services are now running correctly."
else
    log "Some services failed to restart. Please check the logs."
    speak "Warning! Some services failed to restart. Please check the logs."
fi

log "========== RESTART ALL SERVICES COMPLETED =========="