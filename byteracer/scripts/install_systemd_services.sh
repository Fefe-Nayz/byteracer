#!/bin/bash

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export BYTERACER_PATH="${BYTERACER_PATH:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

LOG_FILE="${BYTERACER_LOG_DIR}/install_systemd_services.log"
setup_logging "${LOG_FILE}"

SYSTEMD_DIR="${BYTERACER_PATH}/byteracer/systemd"
BYTERACER_USER="${BYTERACER_USER:-$(stat -c "%U" "${BYTERACER_PATH}" 2>/dev/null || echo pi)}"
BUN_BIN="${BUN_BIN:-$(command -v bun 2>/dev/null || echo "/home/${BYTERACER_USER}/.bun/bin/bun")}"
BUN_DIR="$(dirname "${BUN_BIN}")"

escape_sed_replacement() {
    printf '%s' "$1" | sed -e 's/[\/&|]/\\&/g'
}

install_unit_template() {
    local source_file="$1"
    local destination_file="$2"
    local escaped_path escaped_user escaped_bun_bin escaped_bun_dir

    escaped_path="$(escape_sed_replacement "${BYTERACER_PATH}")"
    escaped_user="$(escape_sed_replacement "${BYTERACER_USER}")"
    escaped_bun_bin="$(escape_sed_replacement "${BUN_BIN}")"
    escaped_bun_dir="$(escape_sed_replacement "${BUN_DIR}")"

    sed \
        -e "s|__BYTERACER_PATH__|${escaped_path}|g" \
        -e "s|__BYTERACER_USER__|${escaped_user}|g" \
        -e "s|__BUN_BIN__|${escaped_bun_bin}|g" \
        -e "s|__BUN_DIR__|${escaped_bun_dir}|g" \
        "${source_file}" | sudo tee "${destination_file}" >/dev/null

    sudo chmod 0644 "${destination_file}"
}

log "========== INSTALL SYSTEMD SERVICES STARTED =========="

if ! systemd_available; then
    log "systemd is not available on this host"
    exit 1
fi

if [ ! -d "${SYSTEMD_DIR}" ]; then
    log "Missing systemd directory: ${SYSTEMD_DIR}"
    exit 1
fi

log "Installing unit files from ${SYSTEMD_DIR}"
log "BYTERACER_PATH=${BYTERACER_PATH}"
log "BYTERACER_USER=${BYTERACER_USER}"
log "BUN_BIN=${BUN_BIN}"
install_unit_template "${SYSTEMD_DIR}/byteracer-eaglecontrol.service" /etc/systemd/system/byteracer-eaglecontrol.service
install_unit_template "${SYSTEMD_DIR}/byteracer-relaytower.service" /etc/systemd/system/byteracer-relaytower.service
install_unit_template "${SYSTEMD_DIR}/byteracer-python.service" /etc/systemd/system/byteracer-python.service
install_unit_template "${SYSTEMD_DIR}/byteracer-startup.service" /etc/systemd/system/byteracer-startup.service
sudo install -m 0644 "${SYSTEMD_DIR}/byteracer-stack.target" /etc/systemd/system/byteracer-stack.target

sudo systemctl daemon-reload
sudo systemctl disable byteracer-stack.target >/dev/null 2>&1 || true
sudo systemctl disable byteracer-eaglecontrol.service byteracer-relaytower.service byteracer-python.service >/dev/null 2>&1 || true
sudo systemctl enable byteracer-startup.service

log "Systemd services installed"
log "Boot orchestrator enabled: byteracer-startup.service"
log "Use: sudo systemctl start byteracer-startup.service"
log "Use: sudo systemctl status byteracer-startup byteracer-eaglecontrol byteracer-relaytower byteracer-python"
log "========== INSTALL SYSTEMD SERVICES COMPLETED =========="
