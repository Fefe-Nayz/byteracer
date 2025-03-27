#!/bin/bash

# Exit if any command fails
set -e

REPO_URL="https://github.com/nayzflux/byteracer.git"
FOLDER_PATH="/home/pi/ByteRacer"
BRANCH="working"

TTS_SCRIPT="$FOLDER_PATH/byteracer/scripts/tts_feedback.py"

say() {
  python3 "$TTS_SCRIPT" "$@" || true
}

echo "=== ByteRacer Startup Script ==="
say "Bonjour, lancement du script de démarrage ByteRacer."

# Create the parent directory if it doesn't exist
mkdir -p "$(dirname "$FOLDER_PATH")"

# Wait for internet connection (up to 60 seconds)
max_wait=60
interval=5
elapsed=0
internet_available=false

echo "Checking for internet connection..."
say "Vérification de la connexion internet..."

while [ $elapsed -lt $max_wait ]; do
    if ping -c 1 -W 2 github.com &> /dev/null; then
        internet_available=true
        echo "Internet connection detected."
        say "Connexion internet détectée."
        break
    fi
    echo "No connection yet. Waiting..."
    sleep $interval
    elapsed=$((elapsed + interval))
done

UPDATED=false
if $internet_available; then
    echo "Internet is available. Proceeding with GitHub fetch."
    say "Mise à jour du dépôt ByteRacer."
    
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
            say "Mise à jour du code ByteRacer effectuée."
        else
            echo "Repository is already up to date."
            say "ByteRacer est déjà à jour."
        fi
    else
        echo "Repository missing or corrupted. Cloning fresh copy..."
        rm -rf "$FOLDER_PATH"
        git clone -b $BRANCH $REPO_URL "$FOLDER_PATH"
        UPDATED=true
        say "Clonage du code ByteRacer terminé."
    fi
else
    echo "No internet connection detected. Skipping GitHub fetch."
    say "Pas de connexion internet, la mise à jour est ignorée."
fi

if [ "$UPDATED" = true ]; then
    echo "Installing dependencies and rebuilding services as necessary..."
    say "Installation des dépendances et compilation."

    # Relaytower (Bun webserver)
    if [ -d "$FOLDER_PATH/relaytower" ]; then
        cd "$FOLDER_PATH/relaytower"
        echo "[relaytower] Installing Bun dependencies..."
        say "Installation des dépendances Relaytower."
        bun install
        echo "[relaytower] Building web server..."
        bun run build
    fi

    # Eaglecontrol (WebSocket server)
    if [ -d "$FOLDER_PATH/eaglecontrol" ]; then
        cd "$FOLDER_PATH/eaglecontrol"
        echo "[eaglecontrol] Installing Bun dependencies..."
        say "Installation des dépendances Eaglecontrol."
        bun install
    fi

    # Byteracer (Python service)
    if [ -d "$FOLDER_PATH/byteracer" ]; then
        cd "$FOLDER_PATH/byteracer"
        if [ -f "requirements.txt" ]; then
            echo "[byteracer] Installing Python dependencies via APT..."
            while IFS= read -r line || [ -n "$line" ]; do
                if [[ -z "$line" ]] || [[ "$line" =~ ^# ]]; then
                    continue
                fi
                pkg=$(echo "$line" | cut -d'=' -f1)
                echo "Installing python3-$pkg"
                sudo apt-get install -y python3-"$pkg"
            done < requirements.txt
        fi
        if [ -f "install.sh" ]; then
            echo "[byteracer] Running install.sh..."
            say "Exécution du script d'installation Byteracer."
            sudo bash ./install.sh
        fi
    fi

    sudo chmod -R 777 /home/pi/ByteRacer/
else
    echo "No repository updates detected; skipping dependency installation."
fi

# Launch the three services in detached screen sessions.
echo "Starting services in screen sessions..."
say "Démarrage des services ByteRacer..."

# Start eaglecontrol service.
screen -dmS eaglecontrol bash -c "cd $FOLDER_PATH/eaglecontrol && bun run start; exec bash"

# Start relaytower service.
screen -dmS relaytower bash -c "cd $FOLDER_PATH/relaytower && bun run start; exec bash"

# Start byteracer service.
screen -dmS byteracer bash -c "cd $FOLDER_PATH/byteracer && sudo python3 main.py; exec bash"

echo "All services have been started."
say "Tous les services ByteRacer sont démarrés. Bon voyage!"
