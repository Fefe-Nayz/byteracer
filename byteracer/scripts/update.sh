#!/bin/bash

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export BYTERACER_PATH="${BYTERACER_PATH:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

LOG_FILE="${BYTERACER_LOG_DIR}/update.log"
setup_logging "${LOG_FILE}"

log "========== UPDATE STARTED =========="
speak "Recherche des mises a jour"

BRANCH="$(get_config ".github.branch" "main")"
REPO_URL="$(get_config ".github.repo_url" "https://github.com/Fefe-Nayz/byteracer.git")"

log "Repository: ${REPO_URL}"
log "Branch: ${BRANCH}"

if [ ! -d "${BYTERACER_PATH}/.git" ]; then
    log "No git repository found at ${BYTERACER_PATH}"
    speak "Echec de la mise a jour. Depot introuvable."
    exit 1
fi

git config --global --add safe.directory "${BYTERACER_PATH}" >/dev/null 2>&1 || true
run_in_dir "${BYTERACER_PATH}" git remote set-url origin "${REPO_URL}" || \
    run_in_dir "${BYTERACER_PATH}" git remote add origin "${REPO_URL}" || \
    log "Could not configure git origin; fetch may fail"

if ! wait_for_internet 30 5; then
    log "Internet unavailable; update skipped"
    speak "Aucune connexion internet. Mise a jour ignoree."
    exit 1
fi

if ! run_in_dir "${BYTERACER_PATH}" git fetch origin "${BRANCH}"; then
    log "Git fetch failed"
    speak "Echec du telechargement de la mise a jour."
    exit 1
fi

LOCAL="$(cd "${BYTERACER_PATH}" && git rev-parse HEAD 2>/dev/null || true)"
REMOTE="$(cd "${BYTERACER_PATH}" && git rev-parse "origin/${BRANCH}" 2>/dev/null || true)"

if [ -z "${REMOTE}" ]; then
    log "Remote branch origin/${BRANCH} not found"
    speak "Echec de la mise a jour. Branche introuvable."
    exit 1
fi

log "Local commit: ${LOCAL}"
log "Remote commit: ${REMOTE}"

if [ "${LOCAL}" = "${REMOTE}" ]; then
    log "Already up to date"
    speak "ByteRacer est deja a jour."
    log "========== UPDATE COMPLETED: NO CHANGES =========="
    exit 0
fi

speak "Installation de la mise a jour"
CONFIG_BACKUP="$(mktemp -d /tmp/byteracer-config.XXXXXX)"
if [ -d "${BYTERACER_PATH}/byteracer/config" ]; then
    cp -a "${BYTERACER_PATH}/byteracer/config/." "${CONFIG_BACKUP}/" 2>/dev/null || true
fi

if ! run_in_dir "${BYTERACER_PATH}" git reset --hard "origin/${BRANCH}"; then
    log "Git reset failed"
    cp -a "${CONFIG_BACKUP}/." "${BYTERACER_PATH}/byteracer/config/" 2>/dev/null || true
    rm -rf "${CONFIG_BACKUP}" 2>/dev/null || true
    speak "Echec de la mise a jour."
    exit 1
fi

mkdir -p "${BYTERACER_PATH}/byteracer/config"
cp -a "${CONFIG_BACKUP}/." "${BYTERACER_PATH}/byteracer/config/" 2>/dev/null || true
rm -rf "${CONFIG_BACKUP}" 2>/dev/null || true

BUILD_EXIT=0
"${SCRIPT_DIR}/setup_python_env.sh" || BUILD_EXIT=$?
build_relaytower_if_needed "true" || BUILD_EXIT=$?
install_eaglecontrol_deps || BUILD_EXIT=$?

if [ "${BUILD_EXIT}" -ne 0 ]; then
    log "Update downloaded, but dependency install or build failed"
    speak "Mise a jour telechargee, mais installation incomplete."
    exit 1
fi

log "Restarting services after update"
if "${SCRIPT_DIR}/restart_services.sh"; then
    speak "Mise a jour installee. ByteRacer est pret."
    log "========== UPDATE COMPLETED =========="
else
    log "Update installed but service restart failed"
    speak "Mise a jour installee, mais redemarrage en echec."
    exit 1
fi
