#!/bin/bash

# Shared shell helpers for ByteRacer maintenance scripts.
# These helpers are intentionally defensive: boot/update scripts should log
# failures and keep going whenever the robot can still start locally.

export BYTERACER_PATH="${BYTERACER_PATH:-/home/pi/ByteRacer}"
export BYTERACER_USER="${BYTERACER_USER:-pi}"
export BYTERACER_LOG_DIR="${BYTERACER_LOG_DIR:-/tmp/byteracer/logs}"
export BYTERACER_POWER_MARKER="${BYTERACER_POWER_MARKER:-${BYTERACER_LOG_DIR}/pending_power_action}"
export BYTERACER_VENV="${BYTERACER_VENV:-${BYTERACER_PATH}/.venv}"
export BYTERACER_PYTHON="${BYTERACER_PYTHON:-${BYTERACER_VENV}/bin/python}"

if ! id "${BYTERACER_USER}" >/dev/null 2>&1; then
    BYTERACER_USER="$(id -un)"
fi

BYTERACER_HOME="$(getent passwd "${BYTERACER_USER}" 2>/dev/null | cut -d: -f6 || true)"
if [ -z "${BYTERACER_HOME}" ]; then
    if [ "${BYTERACER_USER}" = "root" ]; then
        BYTERACER_HOME="/root"
    else
        BYTERACER_HOME="/home/${BYTERACER_USER}"
    fi
fi

export HOME="${HOME:-${BYTERACER_HOME}}"
export PATH="${BYTERACER_HOME}/.bun/bin:${HOME}/.bun/bin:/home/pi/.bun/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

TTS_SCRIPT="${BYTERACER_PATH}/byteracer/tts/speak.py"
CONFIG_FILE="${BYTERACER_PATH}/byteracer/config/settings.json"

byteracer_python() {
    if [ -x "${BYTERACER_PYTHON}" ]; then
        printf '%s\n' "${BYTERACER_PYTHON}"
        return 0
    fi

    if [ -x "${BYTERACER_VENV}/bin/python" ]; then
        printf '%s\n' "${BYTERACER_VENV}/bin/python"
        return 0
    fi

    command -v python3 2>/dev/null || printf '%s\n' "python3"
}

timestamp() {
    date '+%Y-%m-%d %H:%M:%S'
}

log() {
    echo "[$(timestamp)] $*"
}

setup_logging() {
    local log_file="$1"
    mkdir -p "$(dirname "${log_file}")" 2>/dev/null || true
    exec > >(tee -a "${log_file}") 2>&1
}

speak() {
    local text="$1"
    local python_bin
    python_bin="$(byteracer_python)"

    if [ ! -f "${TTS_SCRIPT}" ] || [ -z "${python_bin}" ]; then
        log "TTS unavailable: ${text}"
        return 0
    fi

    timeout 20s "${python_bin}" "${TTS_SCRIPT}" "${text}" >/dev/null 2>&1 || \
        log "TTS failed or timed out: ${text}"
    return 0
}

set_power_action() {
    # Record the pending power action (reboot/shutdown) so the Python controller
    # can make a final spoken announcement when systemd stops it gracefully. The
    # real reboot/power-off only happens minutes later, once every service has
    # stopped, so this marker lets the robot warn people right before it goes.
    local action="$1"
    mkdir -p "$(dirname "${BYTERACER_POWER_MARKER}")" 2>/dev/null || true
    if ! printf '%s\n' "${action}" > "${BYTERACER_POWER_MARKER}" 2>/dev/null; then
        log "Could not write power action marker: ${BYTERACER_POWER_MARKER}"
    fi
}

speak_key() {
    local key="$1"
    shift || true
    local python_bin
    python_bin="$(byteracer_python)"

    if [ ! -f "${TTS_SCRIPT}" ] || [ -z "${python_bin}" ]; then
        log "TTS unavailable for key: ${key}"
        return 0
    fi

    timeout 20s "${python_bin}" "${TTS_SCRIPT}" --key "${key}" "$@" >/dev/null 2>&1 || \
        log "TTS failed or timed out for key: ${key}"
    return 0
}

run_cmd() {
    log "Executing: $*"
    "$@"
    local exit_code=$?
    log "Exit code: ${exit_code}"
    return "${exit_code}"
}

run_in_dir() {
    local dir="$1"
    shift

    if [ ! -d "${dir}" ]; then
        log "Missing directory: ${dir}"
        return 1
    fi

    log "Executing in ${dir}: $*"
    (
        cd "${dir}" || exit 1
        "$@"
    )
    local exit_code=$?
    log "Exit code: ${exit_code}"
    return "${exit_code}"
}

run_as_user() {
    if [ "$(id -un)" = "${BYTERACER_USER}" ]; then
        "$@"
    else
        sudo -u "${BYTERACER_USER}" env PATH="${PATH}" "$@"
    fi
}

run_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
        return $?
    fi

    sudo -n "$@"
    local exit_code=$?
    if [ "${exit_code}" -ne 0 ]; then
        log "Root command failed with exit ${exit_code}: $*"
        log "Run the script with sudo or reinstall ByteRacer systemd services so byteracer-python runs as root."
    fi
    return "${exit_code}"
}

screen_list() {
    run_as_user screen -list 2>/dev/null || true
}

cleanup_dead_screens() {
    run_as_user screen -wipe >/dev/null 2>&1 || true
}

screen_exists() {
    local session="$1"
    screen_list | grep -v "Dead" | grep -Eq "[.]${session}[[:space:]]"
}

systemd_available() {
    command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]
}

systemd_unit_exists() {
    local unit="$1"
    systemd_available && systemctl list-unit-files "${unit}" >/dev/null 2>&1
}

restart_systemd_unit() {
    local unit="$1"
    log "Restarting systemd unit: ${unit}"
    run_root systemctl restart "${unit}"
}

start_systemd_stack() {
    local units=(
        "byteracer-eaglecontrol.service"
        "byteracer-relaytower.service"
        "byteracer-python.service"
    )

    for unit in "${units[@]}"; do
        if ! systemd_unit_exists "${unit}"; then
            return 1
        fi
    done

    for unit in "${units[@]}"; do
        restart_systemd_unit "${unit}" || return 1
    done

    wait_for_port "127.0.0.1" 3001 20 || log "EagleControl did not open port 3001 yet"
    wait_for_port "127.0.0.1" 3000 20 || log "RelayTower did not open port 3000 yet"
    systemctl --no-pager --plain status "${units[@]}" || true
    return 0
}

stop_screen_session() {
    local session="$1"
    local process_pattern="${2:-}"

    cleanup_dead_screens

    if screen_exists "${session}"; then
        log "Stopping screen session: ${session}"
        run_as_user screen -S "${session}" -p 0 -X stuff $'\003' || true
        sleep 4
        run_as_user screen -S "${session}" -X quit || true
        sleep 1
    else
        log "No active screen session named ${session}"
    fi

    if [ -n "${process_pattern}" ]; then
        local pids
        pids="$(pgrep -f "${process_pattern}" 2>/dev/null || true)"
        if [ -n "${pids}" ]; then
            log "Stopping lingering processes for pattern: ${process_pattern}"
            while IFS= read -r pid; do
                [ -z "${pid}" ] && continue
                [ "${pid}" = "$$" ] && continue
                kill "${pid}" >/dev/null 2>&1 || true
            done <<< "${pids}"
            sleep 2
            while IFS= read -r pid; do
                [ -z "${pid}" ] && continue
                [ "${pid}" = "$$" ] && continue
                kill -9 "${pid}" >/dev/null 2>&1 || true
            done <<< "$(pgrep -f "${process_pattern}" 2>/dev/null || true)"
        fi
    fi

    cleanup_dead_screens
}

start_screen_session() {
    local session="$1"
    local dir="$2"
    shift 2
    local command="$*"
    local quoted_dir

    if [ ! -d "${dir}" ]; then
        log "Cannot start ${session}; missing directory: ${dir}"
        return 1
    fi

    printf -v quoted_dir '%q' "${dir}"
    log "Starting ${session}: ${command}"
    run_as_user screen -dmS "${session}" bash -lc "cd ${quoted_dir} && exec ${command}"
}

wait_for_port() {
    local host="$1"
    local port="$2"
    local timeout_seconds="${3:-20}"

    "$(byteracer_python)" - "${host}" "${port}" "${timeout_seconds}" <<'PY'
import socket
import sys
import time

host = sys.argv[1]
port = int(sys.argv[2])
deadline = time.time() + int(sys.argv[3])

while time.time() < deadline:
    try:
        with socket.create_connection((host, port), timeout=1):
            sys.exit(0)
    except OSError:
        time.sleep(0.5)

sys.exit(1)
PY
}

have_internet() {
    "$(byteracer_python)" - <<'PY'
import socket
import sys

for host, port in (("github.com", 443), ("1.1.1.1", 53)):
    try:
        with socket.create_connection((host, port), timeout=3):
            sys.exit(0)
    except OSError:
        pass

sys.exit(1)
PY
}

wait_for_internet() {
    local max_wait="${1:-45}"
    local interval="${2:-5}"
    local elapsed=0

    while [ "${elapsed}" -lt "${max_wait}" ]; do
        if have_internet; then
            return 0
        fi
        log "Internet unavailable; retrying in ${interval}s"
        sleep "${interval}"
        elapsed=$((elapsed + interval))
    done

    return 1
}

get_config() {
    local key="$1"
    local default="$2"
    local python_bin
    python_bin="$(byteracer_python)"

    if [ ! -f "${CONFIG_FILE}" ] || [ -z "${python_bin}" ]; then
        echo "${default}"
        return 0
    fi

    "${python_bin}" - "${CONFIG_FILE}" "${key}" "${default}" <<'PY'
import json
import sys

path, key, default = sys.argv[1:4]

try:
    with open(path, "r", encoding="utf-8") as handle:
        value = json.load(handle)
    for part in key.lstrip(".").split("."):
        value = value[part]
except Exception:
    print(default)
    sys.exit(0)

if isinstance(value, bool):
    print(str(value).lower())
else:
    print(value)
PY
}

build_relaytower_if_needed() {
    local force="${1:-false}"
    local relay_dir="${BYTERACER_PATH}/relaytower"

    if [ ! -d "${relay_dir}" ]; then
        log "RelayTower directory not found; skipping build"
        return 1
    fi

    if [ "${force}" = "true" ] || [ ! -d "${relay_dir}/out" ]; then
        run_in_dir "${relay_dir}" bun install || return 1
        run_in_dir "${relay_dir}" bun run build || return 1
    else
        log "RelayTower build already present"
    fi
}

install_eaglecontrol_deps() {
    local eagle_dir="${BYTERACER_PATH}/eaglecontrol"

    if [ ! -d "${eagle_dir}" ]; then
        log "EagleControl directory not found; skipping dependencies"
        return 1
    fi

    if [ ! -d "${eagle_dir}/node_modules" ]; then
        run_in_dir "${eagle_dir}" bun install || return 1
    else
        log "EagleControl dependencies already present"
    fi
}

start_byteracer_services() {
    local restart_existing="${1:-true}"

    mkdir -p "${BYTERACER_PATH}/byteracer/logs" "${BYTERACER_PATH}/byteracer/config" 2>/dev/null || true
    mkdir -p "${BYTERACER_LOG_DIR}" 2>/dev/null || true
    rm -f /tmp/tts.wav /tmp/tts_*.wav /tmp/tts_startup_*.wav /tmp/tts_vol_*.wav 2>/dev/null || true

    if start_systemd_stack; then
        log "Services launched through systemd"
        return 0
    fi

    log "Systemd units are not installed; using screen fallback"

    if [ "${restart_existing}" = "true" ]; then
        stop_screen_session "byteracer" "python[0-9.]* .*main.py|.venv/bin/python .*main.py"
        stop_screen_session "relaytower" "bun .*server.ts|next start"
        stop_screen_session "eaglecontrol" "bun .*index.ts"
    fi

    start_screen_session "eaglecontrol" "${BYTERACER_PATH}/eaglecontrol" "bun run start" || return 1
    wait_for_port "127.0.0.1" 3001 20 || log "EagleControl did not open port 3001 yet"

    start_screen_session "relaytower" "${BYTERACER_PATH}/relaytower" "bun run start" || return 1
    wait_for_port "127.0.0.1" 3000 30 || log "RelayTower did not open port 3000 yet"

    local python_bin
    python_bin="$(byteracer_python)"
    if [ "$(id -u)" -eq 0 ]; then
        start_screen_session "byteracer" "${BYTERACER_PATH}/byteracer" "env PATH=${PATH} BYTERACER_PYTHON=${python_bin} ${python_bin} main.py" || return 1
    else
        start_screen_session "byteracer" "${BYTERACER_PATH}/byteracer" "sudo -n -E env PATH=${PATH} BYTERACER_PYTHON=${python_bin} ${python_bin} main.py" || return 1
    fi
    sleep 3

    log "Current screen sessions:"
    screen_list
}
