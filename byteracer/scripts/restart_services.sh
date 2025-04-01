#!/bin/bash
# Script to restart all ByteRacer services with TTS feedback

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

echo "Restarting all ByteRacer services..."
speak "Restarting all services. Please wait."

# Stop all services
speak "Stopping WebSocket server."
screen -S eaglecontrol -X quit || true
speak "Stopping web server."
screen -S relaytower -X quit || true
speak "Stopping robot controller."
screen -S byteracer -X quit || true

sleep 2
speak "All services stopped successfully."

# Start eaglecontrol service
speak "Starting WebSocket server."
cd "${BYTERACER_PATH}/eaglecontrol"
screen -dmS eaglecontrol bash -c "bun run start; exec bash"

# Start relaytower service
speak "Starting web server."
cd "${BYTERACER_PATH}/relaytower"
screen -dmS relaytower bash -c "bun run start; exec bash"

# Start byteracer service
speak "Starting robot controller."
cd "${BYTERACER_PATH}/byteracer"
screen -dmS byteracer bash -c "sudo python3 main.py; exec bash"

echo "All services have been restarted."
speak "All services have been restarted successfully."