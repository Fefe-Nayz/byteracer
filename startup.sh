#!/bin/bash

# Define variables
REPO_URL="https://github.com/Fefedu973/byteracer.git"
FOLDER_PATH="/home/pi/ByteRacer"
BRANCH="main"

# # Ensure Bun is installed
# if ! command -v bun &> /dev/null; then
#     echo "Bun not found. Installing..."
#     curl -fsSL https://bun.sh/install | bash
#     export PATH="$HOME/.bun/bin:$PATH"
# fi

# # Ensure tmux is installed
# if ! command -v tmux &> /dev/null; then
#     echo "tmux not found. Installing..."
#     sudo apt update && sudo apt install tmux -y
# fi

# Ensure Bun is available in PATH
export PATH="$HOME/.bun/bin:$PATH"

echo "Starting setup..."

# Ensure the parent directory exists
mkdir -p /home/pi

# Check if the folder is a valid Git repository
if [ -d "$FOLDER_PATH/.git" ]; then
    echo "Pulling latest changes..."
    cd "$FOLDER_PATH" || exit 1
    git fetch origin
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse origin/$BRANCH)

    if [ "$LOCAL" != "$REMOTE" ]; then
        echo "Updating repository..."
        git reset --hard origin/$BRANCH
    else
        echo "Already up to date."
    fi
else
    echo "Repository is missing or corrupted. Cloning fresh copy..."
    rm -rf "$FOLDER_PATH"
    git clone -b $BRANCH $REPO_URL $FOLDER_PATH
fi

# Install dependencies
echo "Installing dependencies..."

# Install dependencies for relaytower (Next.js & Bun webserver)
if [ -d "$FOLDER_PATH/relaytower" ]; then
    cd "$FOLDER_PATH/relaytower" || exit 1
    echo "Installing dependencies for relaytower..."
    bun install
fi

# Install dependencies for eagletower (WebSocket server)
if [ -d "$FOLDER_PATH/eagletower" ]; then
    cd "$FOLDER_PATH/eagletower" || exit 1
    echo "Installing dependencies for eagletower..."
    bun install
fi

# Install dependencies for byteracer (Python script)
if [ -d "$FOLDER_PATH/byteracer" ]; then
    cd "$FOLDER_PATH/byteracer" || exit 1
    if [ -f "requirements.txt" ]; then
        echo "Setting up virtual environment for byteracer..."
        if [ ! -d "venv" ]; then
            python3 -m venv venv
        fi
        echo "Installing Python dependencies for byteracer..."
        source venv/bin/activate
        pip install --upgrade pip
        pip install -r requirements.txt --break-system-packages

        sudo bash ./install.sh
    fi
fi

echo "Starting services..."
sleep 2  # Small delay before launching

# Démarrer des sessions
screen -dmS eaglecontrol bash -c "cd $FOLDER_PATH/eaglecontrol && bun run index.ts; exec bash"
screen -dmS relaytower bash -c "cd $FOLDER_PATH/relaytower && bun dev; exec bash"
screen -dmS byteracer bash -c "cd $FOLDER_PATH/byteracer && sudo python3 main.py; exec bash"

echo "All processes started."
