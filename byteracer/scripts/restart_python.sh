#!/bin/bash
# Script to restart the Python controller with TTS feedback

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

echo "Restarting Python controller..."
speak "Restarting robot controller."

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
if session_exists "byteracer"; then
    echo "Stopping byteracer service..."
    screen -S byteracer -X quit
    sleep 2
    
    # Check if it's still running and try harder to kill it
    if session_exists "byteracer"; then
        echo "Service didn't stop properly, trying forced kill..."
        screen -S byteracer -X kill
        sleep 1
        
        # Check one more time
        if session_exists "byteracer"; then
            echo "Warning: Failed to stop byteracer service!"
            # Try to find and kill the process more forcefully
            PID=$(pgrep -f "python3 main.py" || echo "")
            if [ -n "$PID" ]; then
                echo "Found python process with PID $PID, killing it..."
                sudo kill -9 $PID
                sleep 1
            fi
        fi
    fi
fi

echo "Starting byteracer service..."
speak "Starting robot controller."

# Navigate to correct directory
cd "${BYTERACER_PATH}/byteracer" || {
    echo "Error: Failed to change to directory ${BYTERACER_PATH}/byteracer"
    speak "Error accessing robot controller directory."
    exit 1
}

# Start in a screen session
screen -dmS byteracer bash -c "sudo python3 main.py; exec bash"
sleep 2

# Verify the service started
if session_exists "byteracer"; then
    echo "Python controller has been restarted successfully."
    speak "Robot controller has been restarted successfully."
else
    echo "Error: Failed to start Python controller!"
    speak "Failed to start robot controller. Please check the system logs."
    exit 1
fi