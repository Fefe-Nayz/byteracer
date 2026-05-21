#!/bin/bash

set -uo pipefail

REPO_URL="${REPO_URL:-https://github.com/nayzflux/byteracer.git}"
BRANCH="${BRANCH:-working-2}"
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
    git -C "${TARGET_DIR}" config core.sparseCheckout true
    git -C "${TARGET_DIR}" sparse-checkout init --no-cone
    git -C "${TARGET_DIR}" sparse-checkout set --no-cone "${APP_PATHS[@]}"
    git -C "${TARGET_DIR}" fetch --depth=1 origin "${BRANCH}"
    git -C "${TARGET_DIR}" checkout -B "${BRANCH}" "origin/${BRANCH}"
else
    log "Creating sparse checkout in ${TARGET_DIR}"
    mkdir -p "$(dirname "${TARGET_DIR}")"
    git clone --filter=blob:none --depth=1 --sparse -b "${BRANCH}" "${REPO_URL}" "${TARGET_DIR}"
    git -C "${TARGET_DIR}" sparse-checkout set --no-cone "${APP_PATHS[@]}"
fi

log "Sparse app checkout ready"
