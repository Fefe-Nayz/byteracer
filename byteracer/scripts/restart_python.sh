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

echo "Restarting Python controller..."
speak "Restarting robot controller."

# Stop the service
screen -S byteracer -X quit || true
sleep 1

# Start byteracer service
cd "${BYTERACER_PATH}/byteracer"
screen -dmS byteracer bash -c "sudo python3 main.py; exec bash"

echo "Python controller has been restarted."
speak "Robot controller has been restarted successfully."