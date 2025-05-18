#!/bin/bash
# Startup script with improved TTS functionality that prevents conflicts

# Exit if any command fails
set -e

# Project paths
BYTERACER_PATH="/home/pi/ByteRacer"
TTS_SCRIPT="${BYTERACER_PATH}/byteracer/tts/speak.py"
CONFIG_FILE="${BYTERACER_PATH}/byteracer/config/settings.json"

# Function to speak with TTS
speak() {
    # Use the improved speak.py script with unique temp files
    python3 "${TTS_SCRIPT}" "$1"
}

# Function to get a value from the config file
get_config() {
    local key=$1
    local default=$2
    
    # Check if the config file exists
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "$default"
        return
    fi
    
    # Check if jq is installed
    if ! command -v jq &> /dev/null; then
        echo "$default"
        return
    fi
    
    # Get the value from the config file
    value=$(jq -r "$key" "$CONFIG_FILE" 2>/dev/null)
    
    # Return the default value if the key doesn't exist or value is null
    if [ $? -ne 0 ] || [ "$value" = "null" ]; then
        echo "$default"
    else
        echo "$value"
    fi
}

echo "=== ByteRacer Startup Script ==="
speak "Starting ByteRacer boot sequence"

# Configuration - use config file if available, otherwise use defaults
REPO_URL=$(get_config ".github.repo_url" "https://github.com/nayzflux/byteracer.git")
FOLDER_PATH="/home/pi/ByteRacer"
BRANCH=$(get_config ".github.branch" "working-2")
AUTO_UPDATE=$(get_config ".github.auto_update" "true")

echo "Using GitHub Repository: $REPO_URL"
echo "Using branch: $BRANCH"
echo "Auto update: $AUTO_UPDATE"

# Create the parent directory if it doesn't exist
mkdir -p "$(dirname "$FOLDER_PATH")"

# Wait for internet connection (up to 60 seconds)
speak "Checking for internet connection"
max_wait=60
interval=5
elapsed=0
internet_available=false

echo "Checking for internet connection..."
while [ $elapsed -lt $max_wait ]; do
    if ping -c 1 -W 2 github.com &> /dev/null; then
        internet_available=true
        echo "Internet connection detected."
        speak "Internet connection available"
        break
    fi
    echo "No connection yet. Waiting..."
    sleep $interval
    elapsed=$((elapsed + interval))
done

if ! $internet_available; then
    speak "No internet connection found. Starting in offline mode."
fi

# Check if the repository exists and is valid
UPDATED=false
if $internet_available && [ "$AUTO_UPDATE" = "true" ]; then
    echo "Internet is available. Proceeding with GitHub fetch."
    speak "Checking for software updates"
    
    # Your existing repository check and update code
    if [ -d "$FOLDER_PATH/.git" ]; then
        echo "Repository exists. Checking for updates..."
        cd "$FOLDER_PATH"
        git fetch origin
        LOCAL=$(git rev-parse HEAD)
        REMOTE=$(git rev-parse origin/$BRANCH)
        if [ "$LOCAL" != "$REMOTE" ]; then
            echo "Updates found. Resetting repository to latest commit..."
            speak "Updates found. Installing now."
            git reset --hard origin/$BRANCH
            UPDATED=true
        else
            echo "Repository is already up to date."
            speak "Software is up to date."
        fi
    else
        echo "Repository missing or corrupted. Cloning fresh copy..."
        speak "Installing ByteRacer software for the first time."
        rm -rf "$FOLDER_PATH"
        git clone -b $BRANCH $REPO_URL "$FOLDER_PATH"
        UPDATED=true
    fi

else
    echo "No internet connection detected or auto-update disabled. Skipping GitHub fetch."
fi


# If updates were applied, install/update dependencies and build the web server.
if [ "$UPDATED" = true ]; then
    echo "Installing dependencies and rebuilding services as necessary..."
    speak "Installing dependencies and rebuilding services."

    # --- Relaytower (Bun webserver) ---
    if [ -d "$FOLDER_PATH/relaytower" ]; then
        cd "$FOLDER_PATH/relaytower"
        echo "[relaytower] Installing Bun dependencies..."
        speak "Installing web server dependencies."
        bun install
        echo "[relaytower] Building web server..."
        speak "Building web server."
        sudo bun run build
    fi

    # --- Eaglecontrol (WebSocket server) ---
    if [ -d "$FOLDER_PATH/eaglecontrol" ]; then
        cd "$FOLDER_PATH/eaglecontrol"
        echo "[eaglecontrol] Installing Bun dependencies..."
        speak "Installing WebSocket server dependencies."
        bun install
    fi

    # --- Byteracer (Python service) ---
    if [ -d "$FOLDER_PATH/byteracer" ]; then
        cd "$FOLDER_PATH/byteracer"
        if [ -f "requirements.txt" ]; then
            echo "[byteracer] Installing Python dependencies via APT..."
            speak "Installing Python dependencies."
            # Read each non-empty, non-comment line in requirements.txt.
            while IFS= read -r line || [ -n "$line" ]; do
                # Skip comments and empty lines.
                if [[ -z "$line" ]] || [[ "$line" =~ ^# ]]; then
                    continue
                fi
                # Remove any version specifiers; assume package names match apt package names after "python3-"
                pkg=$(echo "$line" | cut -d'=' -f1)
                echo "Installing python3-$pkg"
                sudo apt-get install -y python3-"$pkg"
            done < requirements.txt
        fi
        # Run the byteracer install script if it exists.
        if [ -f "install.sh" ]; then
            echo "[byteracer] Running install.sh..."
            speak "Running additional installation steps."
            sudo bash ./install.sh
        fi
    fi

    sudo chmod -R 777 /home/pi/ByteRacer/
    speak "Installation complete."

else
    echo "No repository updates detected; skipping dependency installation."
fi

# Create necessary directories
mkdir -p "$FOLDER_PATH/byteracer/logs" "$FOLDER_PATH/byteracer/config" 2>/dev/null || true

# Clean up any leftover TTS temporary files before launching services
echo "Cleaning up temporary TTS files..."
rm -f /tmp/tts.wav /tmp/tts_*.wav

# Launch the three services in detached screen sessions.
echo "Starting services in screen sessions..."
speak "Starting ByteRacer services."

# Start eaglecontrol service.
speak "Starting WebSocket service."
screen -dmS eaglecontrol bash -c "cd $FOLDER_PATH/eaglecontrol && bun run start; exec bash"

# Start relaytower service.
speak "Starting web server."
screen -dmS relaytower bash -c "cd $FOLDER_PATH/relaytower && bun run start; exec bash"

# Start byteracer service.
speak "Starting robot controller."
screen -dmS byteracer bash -c "cd $FOLDER_PATH/byteracer && sudo python3 main.py; exec bash"

echo "All services have been started."
speak "ByteRacer startup complete. Ready to drive."
