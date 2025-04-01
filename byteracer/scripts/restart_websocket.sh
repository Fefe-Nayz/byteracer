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

echo "Restarting WebSocket server (eaglecontrol)..."
speak "Restarting WebSocket service. Please wait."

# Stop the service
screen -S eaglecontrol -X quit || true
sleep 1

# Start eaglecontrol service
cd "${BYTERACER_PATH}/eaglecontrol"
screen -dmS eaglecontrol bash -c "bun run start; exec bash"

echo "WebSocket server has been restarted."
speak "WebSocket server has been restarted successfully."