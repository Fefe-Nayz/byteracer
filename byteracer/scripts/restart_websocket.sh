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

# Create new screen session if it doesn't exist
if ! session_exists "eaglecontrol"; then
    echo "No eaglecontrol screen session found. Creating a new one..."
    speak "Creating new WebSocket server process."
    
    # Navigate to correct directory
    cd "${BYTERACER_PATH}/eaglecontrol" || {
        echo "Error: Failed to change to directory ${BYTERACER_PATH}/eaglecontrol"
        speak "Error accessing WebSocket server directory."
        exit 1
    }
    
    # Start in a new screen session
    screen -dmS eaglecontrol bash -c "cd ${BYTERACER_PATH}/eaglecontrol && bun run start; exec bash"
    sleep 2
    
    # Verify the service started
    if session_exists "eaglecontrol"; then
        echo "WebSocket server has been started successfully."
        speak "WebSocket server has been started successfully."
        exit 0
    else
        echo "Error: Failed to start WebSocket server!"
        speak "Failed to start WebSocket server. Please check the system logs."
        exit 1
    fi
fi

# If we reach here, the screen session exists and we need to restart the service within it
echo "Stopping WebSocket server process gracefully..."
speak "Stopping WebSocket server."

# Send Ctrl+C to the screen session
screen -S eaglecontrol -X stuff $'\003'

# Wait for the process to stop (with timeout)
max_wait=10
counter=0
is_running=true

echo "Waiting for WebSocket process to stop..."
while [ $counter -lt $max_wait ] && [ "$is_running" = true ]; do
    # Check if bun run is still running in the screen
    if ! screen -S eaglecontrol -X hardcopy /tmp/eaglecontrol-screen.txt; then
        echo "Error accessing screen session."
        break
    fi
    
    if grep -q "bun run start" /tmp/eaglecontrol-screen.txt 2>/dev/null; then
        echo "Process still running, waiting... ($counter/$max_wait seconds)"
        counter=$((counter+1))
        sleep 1
    else
        is_running=false
        echo "Process has stopped."
    fi
done

# If process didn't stop, use stronger methods
if [ "$is_running" = true ]; then
    echo "Process didn't stop gracefully within $max_wait seconds, trying stronger methods..."
    
    # Try to kill the bun process without killing the screen
    PID=$(pgrep -f "bun run" || echo "")
    if [ -n "$PID" ]; then
        echo "Found bun process with PID $PID, killing it..."
        sudo kill -9 $PID
        sleep 2
    else
        echo "Warning: Could not find bun process to kill."
    fi
fi

# Restart the service within the same screen session
echo "Restarting WebSocket server in the existing screen session..."
speak "Starting WebSocket server."

# Send command to restart WebSocket server in the screen session
screen -S eaglecontrol -X stuff $"cd ${BYTERACER_PATH}/eaglecontrol && bun run start\n"
sleep 3

# Verify the service is running
screen -S eaglecontrol -X hardcopy /tmp/eaglecontrol-screen.txt
if grep -q "bun run start" /tmp/eaglecontrol-screen.txt 2>/dev/null; then
    echo "WebSocket server has been restarted successfully."
    speak "WebSocket server has been restarted successfully."
    # Clean up temp file
    rm -f /tmp/eaglecontrol-screen.txt
else
    echo "Error: Failed to restart WebSocket server in screen session!"
    speak "Failed to restart WebSocket server. Please check the system logs."
    # Clean up temp file
    rm -f /tmp/eaglecontrol-screen.txt
    exit 1
fi