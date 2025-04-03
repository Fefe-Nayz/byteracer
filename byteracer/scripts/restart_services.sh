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

# Function to check if a screen session exists
session_exists() {
    screen -ls | grep -q "$1"
    return $?
}

# Function to kill a screen session and verify it's gone
kill_session() {
    local session_name="$1"
    if session_exists "$session_name"; then
        echo "Stopping $session_name service..."
        screen -S "$session_name" -X quit
        sleep 1
        if session_exists "$session_name"; then
            echo "Warning: $session_name screen session still exists, trying to kill forcefully..."
            screen -S "$session_name" -X kill
            sleep 1
        fi
        if ! session_exists "$session_name"; then
            echo "$session_name service stopped successfully."
            return 0
        else
            echo "Error: Failed to stop $session_name service!"
            return 1
        fi
    else
        echo "$session_name service is not running, no need to stop."
        return 0
    fi
}

# Function to start a service in a screen session
start_service() {
    local session_name="$1"
    local directory="$2"
    local command="$3"
    local description="$4"
    
    echo "Starting $description..."
    speak "Starting $description."
    
    cd "${BYTERACER_PATH}/$directory" || {
        echo "Error: Failed to change to directory ${BYTERACER_PATH}/$directory"
        speak "Error accessing directory for $description."
        return 1
    }
    
    screen -dmS "$session_name" bash -c "$command; exec bash"
    sleep 2
    
    if session_exists "$session_name"; then
        echo "$description started successfully."
        return 0
    else
        echo "Error: Failed to start $description!"
        speak "Failed to start $description."
        return 1
    fi
}

echo "Restarting all ByteRacer services..."
speak "Restarting all services. Please wait."

# Stop all services
speak "Stopping all services."
kill_session "eaglecontrol" && speak "WebSocket server stopped."
kill_session "relaytower" && speak "Web server stopped."
kill_session "byteracer" && speak "Robot controller stopped."

sleep 2
speak "All services stopped. Now restarting."

# Start services with verification
start_service "eaglecontrol" "eaglecontrol" "bun run start" "WebSocket server"
start_service "relaytower" "relaytower" "bun run start" "Web server"
start_service "byteracer" "byteracer" "sudo python3 main.py" "Robot controller"

# Verify all services are running
all_running=true
for session in "eaglecontrol" "relaytower" "byteracer"; do
    if ! session_exists "$session"; then
        echo "Warning: $session is not running!"
        all_running=false
    fi
done

if [ "$all_running" = true ]; then
    echo "All services have been restarted successfully."
    speak "All services have been restarted successfully."
else
    echo "Some services failed to restart. Please check the logs."
    speak "Warning! Some services failed to restart."
fi