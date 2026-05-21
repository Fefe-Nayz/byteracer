#!/bin/bash

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export BYTERACER_PATH="${BYTERACER_PATH:-${SCRIPT_DIR}}"

# shellcheck source=/dev/null
source "${BYTERACER_PATH}/byteracer/scripts/common.sh"

LOG_FILE="${BYTERACER_LOG_DIR}/startup.log"
setup_logging "${LOG_FILE}"

log "========== BYTERACER STARTUP STARTED =========="
log "Project path: ${BYTERACER_PATH}"
log "Runtime user: ${BYTERACER_USER}"
speak "Starting ByteRacer"

REPO_URL="$(get_config ".github.repo_url" "https://github.com/Fefe-Nayz/byteracer.git")"
BRANCH="$(get_config ".github.branch" "main")"
AUTO_UPDATE="$(get_config ".github.auto_update" "true")"

log "Repository: ${REPO_URL}"
log "Branch: ${BRANCH}"
log "Auto update: ${AUTO_UPDATE}"

UPDATED=false
BUILD_NEEDED=false

if [ "${AUTO_UPDATE}" = "true" ]; then
    log "Checking internet before update"
    if wait_for_internet 45 5; then
        speak "Checking for updates"

        if [ -d "${BYTERACER_PATH}/.git" ]; then
            git config --global --add safe.directory "${BYTERACER_PATH}" >/dev/null 2>&1 || true
            run_in_dir "${BYTERACER_PATH}" git remote set-url origin "${REPO_URL}" || \
                run_in_dir "${BYTERACER_PATH}" git remote add origin "${REPO_URL}" || \
                log "Could not configure git origin; fetch may fail"

            if run_in_dir "${BYTERACER_PATH}" git fetch origin "${BRANCH}"; then
                LOCAL="$(cd "${BYTERACER_PATH}" && git rev-parse HEAD 2>/dev/null || true)"
                REMOTE="$(cd "${BYTERACER_PATH}" && git rev-parse "origin/${BRANCH}" 2>/dev/null || true)"

                if [ -n "${REMOTE}" ] && [ "${LOCAL}" != "${REMOTE}" ]; then
                    log "Update available: ${LOCAL} -> ${REMOTE}"
                    speak "Installing software update"

                    CONFIG_BACKUP="$(mktemp -d /tmp/byteracer-config.XXXXXX)"
                    if [ -d "${BYTERACER_PATH}/byteracer/config" ]; then
                        cp -a "${BYTERACER_PATH}/byteracer/config/." "${CONFIG_BACKUP}/" 2>/dev/null || true
                    fi

                    if run_in_dir "${BYTERACER_PATH}" git reset --hard "origin/${BRANCH}"; then
                        mkdir -p "${BYTERACER_PATH}/byteracer/config"
                        cp -a "${CONFIG_BACKUP}/." "${BYTERACER_PATH}/byteracer/config/" 2>/dev/null || true
                        UPDATED=true
                        BUILD_NEEDED=true
                    else
                        log "Git reset failed; continuing with local copy"
                        speak "Update failed. Starting installed version."
                    fi

                    rm -rf "${CONFIG_BACKUP}" 2>/dev/null || true
                else
                    log "Repository already up to date"
                fi
            else
                log "Git fetch failed; continuing offline"
            fi
        else
            log "No git repository at ${BYTERACER_PATH}; skipping auto update"
        fi
    else
        log "Internet unavailable; starting offline"
        speak "No internet connection. Starting offline."
    fi
else
    log "Auto update disabled"
fi

if [ "${UPDATED}" = "true" ] || [ ! -d "${BYTERACER_PATH}/relaytower/out" ]; then
    BUILD_NEEDED=true
fi

if [ "${BUILD_NEEDED}" = "true" ]; then
    log "Installing dependencies and building services where needed"
    speak "Preparing services"
    build_relaytower_if_needed "true" || log "RelayTower build failed; service start will still be attempted"
    install_eaglecontrol_deps || log "EagleControl dependency install failed; service start will still be attempted"
else
    build_relaytower_if_needed "false" || log "RelayTower build check failed"
    install_eaglecontrol_deps || log "EagleControl dependency check failed"
fi

log "Starting services"
speak "Starting services"
if start_byteracer_services "true"; then
    speak "ByteRacer is ready"
    log "Services launched"
else
    speak "ByteRacer service startup failed"
    log "At least one service failed to launch"
fi

log "========== BYTERACER STARTUP COMPLETED =========="
