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

# Find and kill existing bun process for eaglecontrol (without killing the screen)
PID=$(pgrep -f "bun run .* eaglecontrol" || echo "")
if [ -n "$PID" ]; then
    log "Found WebSocket server process with PID $PID, sending SIGINT (graceful shutdown)..."
    kill -2 $PID  # Send SIGINT (equivalent to Ctrl+C)
    
    # Wait for process to terminate (max 10 seconds)
    COUNTER=0
    while kill -0 $PID 2>/dev/null && [ $COUNTER -lt 10 ]; do
        log "Waiting for WebSocket process to exit... ($COUNTER/10)"
        sleep 1
        COUNTER=$((COUNTER+1))
    done
    
    # Force kill if still running
    if kill -0 $PID 2>/dev/null; then
        log "WebSocket process didn't exit gracefully, force killing..."
        kill -9 $PID
        sleep 2
    else
        log "WebSocket process exited gracefully."
    fi
else
    log "No WebSocket server process found running."
fi

# Check if screen session exists
if ! screen -list | grep -q "eaglecontrol"; then
    log "Creating new eaglecontrol screen session..."
    # Start in a new screen session
    screen -dmS eaglecontrol bash -c "cd ${BYTERACER_PATH}/eaglecontrol && bun run start; exec bash"
else
    log "Restarting WebSocket server in existing screen session..."
    # Send command to restart WebSocket server in the screen session
    screen -S eaglecontrol -X stuff "cd ${BYTERACER_PATH}/eaglecontrol && bun run start^M"
fi

# Give it a moment to start
sleep 3

# Verify the service is running
PID=$(pgrep -f "bun run .* eaglecontrol" || echo "")
if [ -n "$PID" ]; then
    log "WebSocket server has been restarted successfully with PID $PID."
    speak "WebSocket server has been restarted successfully."
else
    log "Error: Failed to restart WebSocket server!"
    speak "Failed to restart WebSocket server. Please check the system logs."
    exit 1
fi

log "========== RESTART WEBSOCKET COMPLETED =========="