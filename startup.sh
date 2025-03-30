#!/bin/bash
# Modified startup script with TTS notifications

# Exit if any command fails
set -e

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

echo "=== ByteRacer Startup Script ==="
speak "Starting ByteRacer boot sequence"

# Configuration
REPO_URL="https://github.com/nayzflux/byteracer.git"
FOLDER_PATH="/home/pi/ByteRacer"
BRANCH="working-2"

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
if $internet_available; then
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
    echo "No internet connection detected. Skipping GitHub fetch."
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
        bun run build
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

# Launch the three services in detached screen sessions.
echo "Starting services in screen sessions..."
speak "Starting ByteRacer services."
pkill -f "python3.*speak.py" || true

# Start eaglecontrol service.
# speak "Starting WebSocket service."
screen -dmS eaglecontrol bash -c "cd $FOLDER_PATH/eaglecontrol && bun run start; exec bash"

# Start relaytower service.
# speak "Starting web server."
screen -dmS relaytower bash -c "cd $FOLDER_PATH/relaytower && bun run start; exec bash"

# Start byteracer service.
# speak "Starting robot controller."
screen -dmS byteracer bash -c "cd $FOLDER_PATH/byteracer && sudo python3 main.py; exec bash"

echo "All services have been started."
# speak "ByteRacer startup complete. Ready to drive."

exit 0