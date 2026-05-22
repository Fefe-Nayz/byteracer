#!/bin/bash

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export BYTERACER_PATH="${BYTERACER_PATH:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

echo "========== ByteRacer Doctor =========="
echo "Time: $(timestamp)"
echo "Path: ${BYTERACER_PATH}"
echo "User: $(id -un)"
echo "Log dir: ${BYTERACER_LOG_DIR}"
echo

echo "---- Git ----"
git -C "${BYTERACER_PATH}" rev-parse --short HEAD 2>/dev/null || true
git -C "${BYTERACER_PATH}" status --short 2>/dev/null || true
echo

echo "---- Runtime Tools ----"
command -v python3 || true
python3 --version 2>/dev/null || true
echo "ByteRacer Python: $(byteracer_python)"
"$(byteracer_python)" --version 2>/dev/null || true
command -v bun || true
bun --version 2>/dev/null || true
command -v nmcli || true
command -v screen || true
echo

echo "---- Python Imports ----"
"$(byteracer_python)" - <<'PY'
import importlib.util

core = [
    "websockets",
    "psutil",
    "openai",
    "requests",
    "speech_recognition",
    "sox",
    "picarx",
    "robot_hat",
    "vilib",
    "picamera2",
    "libcamera",
    "cv2",
    "numpy",
    "PIL",
    "pygame",
    "pyaudio",
    "flask",
    "imutils",
    "qrcode",
    "pyzbar",
    "readchar",
    "smbus2",
    "gpiozero",
    "spidev",
    "serial",
    "ultralytics",
    "ncnn",
    "torch",
    "google.protobuf",
]

optional_unsupported = [
    "mediapipe",
    "tflite_runtime",
]

for name in core:
    print(f"{name}: {'OK' if importlib.util.find_spec(name) else 'MISSING'}")

for name in optional_unsupported:
    print(f"{name}: {'OK' if importlib.util.find_spec(name) else 'MISSING'} (optional/unsupported on Python 3.13)")
PY
echo

echo "---- Network ----"
ip -brief address 2>/dev/null || true
nmcli -t -f NAME,DEVICE,TYPE connection show --active 2>/dev/null || true
echo

echo "---- Ports ----"
"$(byteracer_python)" - <<'PY'
import socket

for port in (3000, 3001, 9000):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            print(f"{port}: open")
    except OSError:
        print(f"{port}: closed")
PY
echo

echo "---- Screen ----"
screen_list
echo

echo "---- Systemd ----"
if systemd_available; then
    systemctl --no-pager --plain status \
        byteracer-startup.service \
        byteracer-eaglecontrol.service \
        byteracer-relaytower.service \
        byteracer-python.service 2>/dev/null || true
else
    echo "systemd unavailable"
fi
echo

echo "---- Processes ----"
pgrep -af "python[0-9.]* .*main.py|.venv/bin/python .*main.py|bun .*index.ts|bun .*server.ts|next start" || true
echo

echo "---- Recent Logs ----"
for log_file in \
    "${BYTERACER_LOG_DIR}/startup.log" \
    "${BYTERACER_LOG_DIR}/restart_services.log" \
    "${BYTERACER_LOG_DIR}/update.log" \
    "${BYTERACER_PATH}/byteracer/logs/startup.log"; do
    if [ -f "${log_file}" ]; then
        echo "--- ${log_file} ---"
        tail -n 20 "${log_file}"
    fi
done

echo "========== Doctor Complete =========="
