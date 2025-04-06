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
    # Execute the command and capture its output while logging it
    output=$(eval "$cmd" 2>&1)
    exit_code=$?
    
    # Log the command output with timestamp for each line
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

# Find and kill existing bun process for relaytower (without killing the screen)
PID=$(pgrep -f "bun run .* relaytower" || echo "")
if [ -n "$PID" ]; then
    log "Found Web server process with PID $PID, sending SIGINT (graceful shutdown)..."
    run_cmd "kill -2 $PID"  # Send SIGINT (equivalent to Ctrl+C)
    
    # Wait for process to terminate (max 10 seconds)
    COUNTER=0
    while kill -0 $PID 2>/dev/null && [ $COUNTER -lt 10 ]; do
        log "Waiting for Web server process to exit... ($COUNTER/10)"
        sleep 1
        COUNTER=$((COUNTER+1))
    done
    
    # Force kill if still running
    if kill -0 $PID 2>/dev/null; then
        log "Web server process didn't exit gracefully, force killing..."
        run_cmd "kill -9 $PID"
        sleep 2
    else
        log "Web server process exited gracefully."
    fi
else
    log "No Web server process found running."
fi

# Check if screen session exists
if ! run_cmd "screen -list" | grep -q "relaytower"; then
    log "Creating new relaytower screen session..."
    # Start in a new screen session
    run_cmd "screen -dmS relaytower bash -c \"cd ${BYTERACER_PATH}/relaytower && bun run start; exec bash\""
else
    log "Restarting Web server in existing screen session..."
    # Send command to restart Web server in the screen session
    run_cmd "screen -S relaytower -X stuff \"cd ${BYTERACER_PATH}/relaytower && bun run start^M\""
fi

# Give it a moment to start
log "Waiting for process to start..."
sleep 3

# Verify the service is running
PID=$(pgrep -f "bun run .* relaytower" || echo "")
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