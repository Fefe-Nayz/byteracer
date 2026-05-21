#!/bin/bash

set -uo pipefail

REPO_URL="${REPO_URL:-https://github.com/Fefe-Nayz/byteracer.git}"
BRANCH="${BRANCH:-main}"
TARGET_DIR="${TARGET_DIR:-/home/pi/ByteRacer}"

APP_PATHS=(
    "/byteracer/"
    "/eaglecontrol/"
    "/relaytower/"
    "/startup.sh"
    "/README.md"
    "/.gitattributes"
    "/.gitignore"
)

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

if [ -d "${TARGET_DIR}/.git" ]; then
    log "Updating existing sparse checkout in ${TARGET_DIR}"
    log "Application source: ${REPO_URL} (${BRANCH})"
    git -C "${TARGET_DIR}" remote set-url origin "${REPO_URL}" || \
        git -C "${TARGET_DIR}" remote add origin "${REPO_URL}"
    git -C "${TARGET_DIR}" config core.sparseCheckout true
    git -C "${TARGET_DIR}" sparse-checkout init --no-cone
    git -C "${TARGET_DIR}" sparse-checkout set --no-cone "${APP_PATHS[@]}"
    git -C "${TARGET_DIR}" fetch --depth=1 origin "${BRANCH}"
    git -C "${TARGET_DIR}" checkout -B "${BRANCH}" "origin/${BRANCH}"
else
    log "Creating sparse checkout in ${TARGET_DIR}"
    log "Application source: ${REPO_URL} (${BRANCH})"
    mkdir -p "$(dirname "${TARGET_DIR}")"
    git clone --filter=blob:none --depth=1 --sparse -b "${BRANCH}" "${REPO_URL}" "${TARGET_DIR}"
    git -C "${TARGET_DIR}" sparse-checkout set --no-cone "${APP_PATHS[@]}"
fi

required_files=(
    "${TARGET_DIR}/startup.sh"
    "${TARGET_DIR}/byteracer/scripts/common.sh"
    "${TARGET_DIR}/byteracer/scripts/install_systemd_services.sh"
    "${TARGET_DIR}/relaytower/package.json"
    "${TARGET_DIR}/eaglecontrol/package.json"
)

for file in "${required_files[@]}"; do
    if [ ! -f "${file}" ]; then
        log "ERROR: required application file is missing after checkout: ${file}"
        exit 1
    fi
done

log "Sparse app checkout ready"
