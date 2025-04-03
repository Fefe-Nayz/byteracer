#!/bin/bash
# Script to restart the WebSocket server with TTS feedback

# Project paths
BYTERACER_PATH="/home/pi/ByteRacer"
TTS_SCRIPT="${BYTERACER_PATH}/byteracer/tts/speak.py"

# Function to speak with TTS
speak() {
    if [ -f "$TTS_SCRIPT" ]; then
        python3 "$TTS_SCRIPT" "$1"
    else
        echo "TTS script not found: $TTS_SCRIPT"
    fi
}

# Function to check if a screen session exists
session_exists() {
    screen -ls | grep -q "$1"
    return $?
}

echo "Restarting WebSocket server (eaglecontrol)..."
speak "Restarting WebSocket service. Please wait."

# Check if screen command exists
if ! command -v screen &> /dev/null; then
    echo "Error: 'screen' command not found. Installing screen..."
    speak "Error: screen program not found. Attempting to install."
    sudo apt-get update && sudo apt-get install -y screen
    if ! command -v screen &> /dev/null; then
        echo "Failed to install screen. Aborting."
        speak "Failed to install screen. Cannot restart services."
        exit 1
    fi
fi

# Stop the service if it's running
if session_exists "eaglecontrol"; then
    echo "Stopping eaglecontrol service..."
    screen -S eaglecontrol -X quit
    sleep 2
    
    # Check if it's still running and try harder to kill it
    if session_exists "eaglecontrol"; then
        echo "Service didn't stop properly, trying forced kill..."
        screen -S eaglecontrol -X kill
        sleep 1
        
        # Check one more time
        if session_exists "eaglecontrol"; then
            echo "Warning: Failed to stop eaglecontrol service!"
            # Try to find and kill the process more forcefully
            PID=$(pgrep -f "bun run" || echo "")
            if [ -n "$PID" ]; then
                echo "Found bun process with PID $PID, killing it..."
                sudo kill -9 $PID
                sleep 1
            fi
        fi
    fi
else
    echo "No eaglecontrol service found running. Starting fresh instance."
fi

echo "Starting eaglecontrol service..."
speak "Starting WebSocket server."

# Navigate to correct directory
cd "${BYTERACER_PATH}/eaglecontrol" || {
    echo "Error: Failed to change to directory ${BYTERACER_PATH}/eaglecontrol"
    speak "Error accessing WebSocket server directory."
    exit 1
}

# Start in a screen session
screen -dmS eaglecontrol bash -c "bun run start; exec bash"
sleep 2

# Verify the service started
if session_exists "eaglecontrol"; then
    echo "WebSocket server has been restarted successfully."
    speak "WebSocket server has been restarted successfully."
else
    echo "Error: Failed to start WebSocket server!"
    speak "Failed to start WebSocket server. Please check the system logs."
    exit 1
fi