#!/bin/bash
# /home/pi/ByteRacer/byteracer/scripts/restart_services.sh
set -e

TTS_SCRIPT="/home/pi/ByteRacer/byteracer/scripts/tts_feedback.py"

say() {
  python3 "$TTS_SCRIPT" "$@" || true
}

echo "Restarting ByteRacer services..."
say "Redémarrage de tous les services ByteRacer."

# Stop
screen -S eaglecontrol -X quit || true
screen -S relaytower -X quit || true
screen -S byteracer -X quit || true

sleep 2

# Start eaglecontrol
cd /home/pi/ByteRacer/eaglecontrol
screen -dmS eaglecontrol bash -c "bun run start; exec bash"

# Start relaytower
cd /home/pi/ByteRacer/relaytower
screen -dmS relaytower bash -c "bun run build && bun run start; exec bash"

# Start byteracer
cd /home/pi/ByteRacer/byteracer
screen -dmS byteracer bash -c "sudo python3 main.py; exec bash"

echo "All services restarted."
say "Tous les services ByteRacer ont été redémarrés avec succès."
