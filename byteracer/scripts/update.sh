#!/bin/bash
# Update script for ByteRacer with TTS feedback

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

echo "Updating ByteRacer components..."
speak "Starting update process for ByteRacer."

cd "${BYTERACER_PATH}"

# Check for git updates
echo "Checking for updates from GitHub..."
speak "Checking for updates from GitHub."

git fetch
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    echo "Already up to date. No update needed."
    speak "ByteRacer is already up to date."
    exit 0
fi

# Updates found, pull changes
echo "Updates found. Pulling latest code..."
speak "Updates found. Downloading latest version."
git pull

# Update relaytower (Bun webserver)
if [ -d "relaytower" ]; then
    cd relaytower
    echo "[relaytower] Installing dependencies..."
    speak "Updating web server dependencies."
    bun install
    echo "[relaytower] Building web server..."
    speak "Building web server."
    bun run build
    cd ..
fi

# Update eaglecontrol (WebSocket server)
if [ -d "eaglecontrol" ]; then
    cd eaglecontrol
    echo "[eaglecontrol] Installing dependencies..."
    speak "Updating WebSocket server dependencies."
    bun install
    cd ..
fi

# Update byteracer Python dependencies
if [ -d "byteracer" ]; then
    cd byteracer
    if [ -f "requirements.txt" ]; then
        echo "[byteracer] Installing Python dependencies..."
        speak "Updating Python dependencies."
        while IFS= read -r line || [ -n "$line" ]; do
            # Skip comments and empty lines
            if [[ -z "$line" ]] || [[ "$line" =~ ^# ]]; then
                continue
            fi
            # Remove any version specifiers
            pkg=$(echo "$line" | cut -d'=' -f1)
            echo "Installing python3-$pkg"
            sudo apt-get install -y python3-"$pkg"
        done < requirements.txt
    fi
    if [ -f "install.sh" ]; then
        echo "[byteracer] Running install script..."
        speak "Running additional installation steps."
        sudo bash ./install.sh
    fi
    cd ..
fi

echo "Update completed. Restarting services..."
speak "Update completed. Restarting all services to apply the changes."

# Restart all services
sudo bash "${BYTERACER_PATH}/byteracer/scripts/restart_services.sh"

echo "Update and restart complete."
speak "All updates have been installed and services restarted. ByteRacer is ready to use."