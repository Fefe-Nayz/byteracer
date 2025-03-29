#!/bin/bash
# Script to restart the Web Server with TTS feedback

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

echo "Restarting Web Server (relaytower)..."
speak "Restarting Web Server."

# Stop the service
screen -S relaytower -X quit || true
sleep 1

# Start relaytower service
cd "${BYTERACER_PATH}/relaytower"
screen -dmS relaytower bash -c "bun run start; exec bash"

echo "Web Server has been restarted."
speak "Web Server has been restarted successfully."