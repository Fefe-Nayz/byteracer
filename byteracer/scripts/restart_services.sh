#!/bin/bash
# Script to restart all ByteRacer services with TTS feedback

# Project paths
BYTERACER_PATH="/home/pi/ByteRacer"
TTS_SCRIPT="${BYTERACER_PATH}/byteracer/tts/speak.py"
SCRIPTS_PATH="${BYTERACER_PATH}/byteracer/scripts"

# Function to speak with TTS
speak() {
    if [ -f "$TTS_SCRIPT" ]; then
        python3 "$TTS_SCRIPT" "$1"
    else
        echo "TTS script not found: $TTS_SCRIPT"
    fi
}

# Make sure all scripts are executable
chmod +x "${SCRIPTS_PATH}/restart_websocket.sh"
chmod +x "${SCRIPTS_PATH}/restart_web_server.sh"
chmod +x "${SCRIPTS_PATH}/restart_python.sh"

echo "Restarting all ByteRacer services..."
speak "Restarting all ByteRacer services. This may take a moment."

# Restart WebSocket server (eaglecontrol)
"${SCRIPTS_PATH}/restart_websocket.sh"

# Restart Web server (relaytower)
"${SCRIPTS_PATH}/restart_web_server.sh"

# Restart Python controller (byteracer)
"${SCRIPTS_PATH}/restart_python.sh"

# Final message
echo "All services restart process completed."
speak "All services restart process completed."

# Function to check if a screen session exists
session_exists() {
    screen -ls | grep -q "$1"
    return $?
}

# Verify all services are running
all_running=true
for session in "eaglecontrol" "relaytower" "byteracer"; do
    if ! session_exists "$session"; then
        echo "Warning: $session is not running!"
        speak "Warning! $session is not running."
        all_running=false
    fi
done

if [ "$all_running" = true ]; then
    echo "All services are now running correctly."
    speak "All services are now running correctly."
else
    echo "Some services failed to restart. Please check the logs."
    speak "Warning! Some services failed to restart. Please check the logs."
fi