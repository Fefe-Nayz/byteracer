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

# Find and kill existing python process (without killing the screen)
PID=$(pgrep -f "python3 main.py" || echo "")
if [ -n "$PID" ]; then
    log "Found Python controller process with PID $PID, sending SIGINT (graceful shutdown)..."
    kill -2 $PID  # Send SIGINT (equivalent to Ctrl+C)
    
    # Wait for process to terminate (max 10 seconds)
    COUNTER=0
    while kill -0 $PID 2>/dev/null && [ $COUNTER -lt 10 ]; do
        log "Waiting for Python process to exit... ($COUNTER/10)"
        sleep 1
        COUNTER=$((COUNTER+1))
    done
    
    # Force kill if still running
    if kill -0 $PID 2>/dev/null; then
        log "Python process didn't exit gracefully, force killing..."
        kill -9 $PID
        sleep 2
    else
        log "Python process exited gracefully."
    fi
else
    log "No Python controller process found running."
fi

# Check if screen session exists
if ! screen -list | grep -q "byteracer"; then
    log "Creating new byteracer screen session..."
    # Start in a new screen session
    screen -dmS byteracer bash -c "cd ${BYTERACER_PATH}/byteracer && sudo python3 main.py; exec bash"
else
    log "Restarting Python controller in existing screen session..."
    # Send command to restart Python in the screen session
    screen -S byteracer -X stuff "cd ${BYTERACER_PATH}/byteracer && sudo python3 main.py^M"
fi

# Give it a moment to start
sleep 3

# Verify the service is running
PID=$(pgrep -f "python3 main.py" || echo "")
if [ -n "$PID" ]; then
    log "Python controller has been restarted successfully with PID $PID."
    speak "Robot controller has been restarted successfully."
else
    log "Error: Failed to restart Python controller!"
    speak "Failed to restart robot controller. Please check the system logs."
    exit 1
fi

log "========== RESTART PYTHON COMPLETED =========="