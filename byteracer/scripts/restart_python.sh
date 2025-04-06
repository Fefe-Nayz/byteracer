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

# Create new screen session if it doesn't exist
if ! session_exists "byteracer"; then
    echo "No byteracer screen session found. Creating a new one..."
    speak "Creating new robot controller process."
    
    # Navigate to correct directory
    cd "${BYTERACER_PATH}/byteracer" || {
        echo "Error: Failed to change to directory ${BYTERACER_PATH}/byteracer"
        speak "Error accessing robot controller directory."
        exit 1
    }
    
    # Start in a new screen session
    screen -dmS byteracer bash -c "cd ${BYTERACER_PATH}/byteracer && sudo python3 main.py; exec bash"
    sleep 2
    
    # Verify the service started
    if session_exists "byteracer"; then
        echo "Python controller has been started successfully."
        speak "Robot controller has been started successfully."
        exit 0
    else
        echo "Error: Failed to start Python controller!"
        speak "Failed to start robot controller. Please check the system logs."
        exit 1
    fi
fi

# If we reach here, the screen session exists and we need to restart the service within it
echo "Stopping Python controller process gracefully..."
speak "Stopping robot controller."

# Send Ctrl+C to the screen session
screen -S byteracer -X stuff $'\003'

# Wait for the process to stop (with timeout)
max_wait=10
counter=0
is_running=true

echo "Waiting for Python process to stop..."
while [ $counter -lt $max_wait ] && [ "$is_running" = true ]; do
    # Check if python3 main.py is still running in the screen
    if ! screen -S byteracer -X hardcopy /tmp/byteracer-screen.txt; then
        echo "Error accessing screen session."
        break
    fi
    
    if grep -q "python3 main.py" /tmp/byteracer-screen.txt 2>/dev/null; then
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
    
    # Try to kill the Python process without killing the screen
    PID=$(pgrep -f "python3 main.py" || echo "")
    if [ -n "$PID" ]; then
        echo "Found python process with PID $PID, killing it..."
        sudo kill -9 $PID
        sleep 2
    else
        echo "Warning: Could not find Python process to kill."
    fi
fi

# Restart the service within the same screen session
echo "Restarting Python controller in the existing screen session..."
speak "Starting robot controller."

# Send command to restart Python in the screen session
screen -S byteracer -X stuff $"cd ${BYTERACER_PATH}/byteracer && sudo python3 main.py\n"
sleep 3

# Verify the service is running
screen -S byteracer -X hardcopy /tmp/byteracer-screen.txt
if grep -q "python3 main.py" /tmp/byteracer-screen.txt 2>/dev/null; then
    echo "Python controller has been restarted successfully."
    speak "Robot controller has been restarted successfully."
    # Clean up temp file
    rm -f /tmp/byteracer-screen.txt
else
    echo "Error: Failed to restart Python controller in screen session!"
    speak "Failed to restart robot controller. Please check the system logs."
    # Clean up temp file
    rm -f /tmp/byteracer-screen.txt
    exit 1
fi