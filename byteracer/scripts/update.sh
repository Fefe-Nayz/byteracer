#!/bin/bash
# /home/pi/ByteRacer/byteracer/scripts/update.sh
set -e

TTS_SCRIPT="/home/pi/ByteRacer/byteracer/scripts/tts_feedback.py"

say() {
  python3 "$TTS_SCRIPT" "$@" || true
}

echo "Updating ByteRacer..."
say "Mise à jour de ByteRacer en cours."

cd /home/pi/ByteRacer

# Update relaytower (Bun webserver)
if [ -d "relaytower" ]; then
    cd relaytower
    echo "[relaytower] Installing dependencies..."
    say "Installation des dépendances Relaytower."
    bun install
    echo "[relaytower] Building web server..."
    bun run build
    cd ..
fi

# Update eaglecontrol (WebSocket server)
if [ -d "eaglecontrol" ]; then
    cd eaglecontrol
    echo "[eaglecontrol] Installing dependencies..."
    say "Installation des dépendances Eaglecontrol."
    bun install
    cd ..
fi

# Update byteracer Python dependencies
if [ -d "byteracer" ]; then
    cd byteracer
    if [ -f "requirements.txt" ]; then
        echo "[byteracer] Installing Python dependencies..."
        say "Installation des dépendances Python de Byteracer."
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
        echo "[byteracer] Running install script..."
        say "Exécution du script d'installation Byteracer."
        sudo bash ./install.sh
    fi
    cd ..
fi

echo "Update completed. Restarting services..."
say "Mise à jour terminée. Redémarrage des services."
sudo bash /home/pi/ByteRacer/byteracer/scripts/restart_services.sh
