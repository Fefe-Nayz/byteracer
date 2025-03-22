#!/bin/bash

# Exit if any command fails
set -e

# CONFIGURATION
REPO_URL="https://github.com/nayzflux/byteracer.git"
FOLDER_PATH="/home/pi/ByteRacer"
BRANCH="main"

echo "=== ByteRacer Startup Script ==="

# Ensure Bun is available in PATH
export PATH="$HOME/.bun/bin:$PATH"

# Create the parent directory if it doesn't exist
mkdir -p "$(dirname "$FOLDER_PATH")"

# Check if the repository exists and is valid
UPDATED=false
if [ -d "$FOLDER_PATH/.git" ]; then
    echo "Repository exists. Checking for updates..."
    cd "$FOLDER_PATH"
    git fetch origin
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse origin/$BRANCH)
    if [ "$LOCAL" != "$REMOTE" ]; then
        echo "Updates found. Resetting repository to latest commit..."
        git reset --hard origin/$BRANCH
        UPDATED=true
    else
        echo "Repository is already up to date."
    fi
else
    echo "Repository missing or corrupted. Cloning fresh copy..."
    rm -rf "$FOLDER_PATH"
    git clone -b $BRANCH $REPO_URL "$FOLDER_PATH"
    UPDATED=true
fi

# If updates were applied, install/update dependencies and build the web server.
if [ "$UPDATED" = true ]; then
    echo "Installing dependencies and rebuilding services as necessary..."

    # --- Relaytower (Bun webserver) ---
    if [ -d "$FOLDER_PATH/relaytower" ]; then
        cd "$FOLDER_PATH/relaytower"
        echo "[relaytower] Installing Bun dependencies..."
        bun install
        echo "[relaytower] Building web server..."
        bun run build
    fi

    # --- Eaglecontrol (WebSocket server) ---
    if [ -d "$FOLDER_PATH/eaglecontrol" ]; then
        cd "$FOLDER_PATH/eaglecontrol"
        echo "[eaglecontrol] Installing Bun dependencies..."
        bun install
    fi

    # --- Byteracer (Python service) ---
    if [ -d "$FOLDER_PATH/byteracer" ]; then
        cd "$FOLDER_PATH/byteracer"
        if [ -f "requirements.txt" ]; then
            echo "[byteracer] Installing Python dependencies via APT..."
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
            sudo bash ./install.sh
        fi
    fi
else
    echo "No repository updates detected; skipping dependency installation."
fi

# Launch the three services in detached screen sessions.
echo "Starting services in screen sessions..."

# Start eaglecontrol service.
screen -dmS eaglecontrol bash -c "cd $FOLDER_PATH/eaglecontrol && bun run start; exec bash"

# Start relaytower service.
screen -dmS relaytower bash -c "cd $FOLDER_PATH/relaytower && bun run start; exec bash"

# Start byteracer service.
screen -dmS byteracer bash -c "cd $FOLDER_PATH/byteracer && sudo python3 main.py; exec bash"

echo "All services have been started."
