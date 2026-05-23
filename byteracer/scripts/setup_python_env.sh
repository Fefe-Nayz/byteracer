#!/bin/bash

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export BYTERACER_PATH="${BYTERACER_PATH:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

REQUIREMENTS_FILE="${REQUIREMENTS_FILE:-${BYTERACER_PATH}/byteracer/requirements.txt}"
PIP_TMP_DIR="${PIP_TMP_DIR:-/var/tmp/byteracer-pip}"
PYTORCH_CPU_NUMPY="${PYTORCH_CPU_NUMPY:-numpy==2.2.6}"
PYTORCH_CPU_INDEX_URL="${PYTORCH_CPU_INDEX_URL:-https://download.pytorch.org/whl/cpu}"
PYTORCH_CPU_TORCH="${PYTORCH_CPU_TORCH:-torch==2.12.0+cpu}"
PYTORCH_CPU_TORCHVISION="${PYTORCH_CPU_TORCHVISION:-torchvision==0.27.0+cpu}"
FORCE_PYTHON_DEPS="${FORCE_PYTHON_DEPS:-false}"
PIPER_DATA_DIR="${BYTERACER_PIPER_DATA_DIR:-${BYTERACER_VENV}/piper-voices}"
PIPER_VOICES="${PIPER_VOICES:-en_US-lessac-medium en_GB-alan-medium fr_FR-siwis-medium}"
SUPERTONIC_CACHE_DIR="${SUPERTONIC_CACHE_DIR:-${BYTERACER_VENV}/supertonic-cache}"

VENV_DIR="${BYTERACER_VENV}"
PYTHON_BIN="${VENV_DIR}/bin/python"
STAMP_FILE="${VENV_DIR}/.byteracer-python-env.sha256"
PYTORCH_CPU_READY=false

run_as_app_user() {
    if [ "$(id -u)" -eq 0 ] && id "${BYTERACER_USER}" >/dev/null 2>&1; then
        sudo -u "${BYTERACER_USER}" env HOME="/home/${BYTERACER_USER}" PATH="${PATH}" "$@"
    else
        "$@"
    fi
}

pip_install() {
    run_as_app_user env TMPDIR="${PIP_TMP_DIR}" "${PYTHON_BIN}" -m pip install "$@"
}

dependency_signature() {
    {
        sha256sum "${REQUIREMENTS_FILE}" 2>/dev/null || true
        printf '%s\n' "${PYTORCH_CPU_NUMPY}"
        printf '%s\n' "${PYTORCH_CPU_INDEX_URL}"
        printf '%s\n' "${PYTORCH_CPU_TORCH}"
        printf '%s\n' "${PYTORCH_CPU_TORCHVISION}"
        printf '%s\n' "${PIPER_VOICES}"
        printf '%s\n' "${SUPERTONIC_CACHE_DIR}"
    } | sha256sum | awk '{ print $1 }'
}

verify_python_stack() {
    "${PYTHON_BIN}" - <<'PY'
import numpy
numpy.zeros((1,), dtype=float)

import torch
import torchvision
import ultralytics
import ncnn
import piper
import supertonic
from importlib.metadata import version

print(f"numpy={numpy.__version__} {numpy.__file__}")
print(f"torch={torch.__version__}")
print(f"torchvision={torchvision.__version__}")
print(f"ultralytics={ultralytics.__version__}")
print(f"ncnn={getattr(ncnn, '__version__', 'unknown')}")
print("piper=OK")
print(f"supertonic={version('supertonic')}")
PY
}

prepare_venv() {
    [ -f "${REQUIREMENTS_FILE}" ] || {
        log "Missing Python requirements file: ${REQUIREMENTS_FILE}"
        return 1
    }

    if [ ! -x "${PYTHON_BIN}" ]; then
        log "Creating ByteRacer Python venv: ${VENV_DIR}"
        run_as_app_user python3 -m venv --system-site-packages "${VENV_DIR}" || return 1
    else
        log "Using ByteRacer Python venv: ${VENV_DIR}"
    fi

    if [ "$(id -u)" -eq 0 ]; then
        sudo mkdir -p "${PIP_TMP_DIR}"
        sudo chown "${BYTERACER_USER}:${BYTERACER_USER}" "${PIP_TMP_DIR}" 2>/dev/null || true
        sudo -u "${BYTERACER_USER}" find "${PIP_TMP_DIR}" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + 2>/dev/null || true
    else
        mkdir -p "${PIP_TMP_DIR}" 2>/dev/null || PIP_TMP_DIR="$(mktemp -d /tmp/byteracer-pip.XXXXXX)"
        find "${PIP_TMP_DIR}" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + 2>/dev/null || true
    fi

    return 0
}

install_pytorch_cpu_stack() {
    if [ "${PYTORCH_CPU_READY}" = "true" ]; then
        return 0
    fi

    log "Installing pip NumPy wheel for ByteRacer venv"
    pip_install --no-cache-dir --ignore-installed --only-binary=:all: "${PYTORCH_CPU_NUMPY}" || return 1

    log "Installing PyTorch CPU wheels for ByteRacer venv"
    pip_install --no-cache-dir \
        --index-url "${PYTORCH_CPU_INDEX_URL}" \
        "${PYTORCH_CPU_TORCH}" \
        "${PYTORCH_CPU_TORCHVISION}" || return 1

    PYTORCH_CPU_READY=true
}

install_requirement() {
    local dep="$1"
    local pip_options=(--no-cache-dir)

    case "${dep}" in
        torch*|torchvision*)
            log "Skipping ${dep}; PyTorch is managed through CPU wheels"
            return 0
            ;;
        numpy*)
            pip_install --no-cache-dir --ignore-installed --only-binary=:all: "${dep}"
            return $?
            ;;
        ultralytics*)
            install_pytorch_cpu_stack || return 1
            ;;
        openai)
            pip_options+=(--ignore-installed)
            ;;
    esac

    pip_install "${pip_options[@]}" "${dep}"
}

install_piper_voices() {
    local voice

    mkdir -p "${PIPER_DATA_DIR}" 2>/dev/null || true
    if [ "$(id -u)" -eq 0 ]; then
        sudo chown -R "${BYTERACER_USER}:${BYTERACER_USER}" "${PIPER_DATA_DIR}" 2>/dev/null || true
    fi

    log "Installing Piper voice models into ${PIPER_DATA_DIR}"
    for voice in ${PIPER_VOICES}; do
        if [ -f "${PIPER_DATA_DIR}/${voice}.onnx" ]; then
            log "Piper voice already installed: ${voice}"
            continue
        fi

        run_as_app_user env BYTERACER_PIPER_DATA_DIR="${PIPER_DATA_DIR}" \
            "${PYTHON_BIN}" -m piper.download_voices --data-dir "${PIPER_DATA_DIR}" "${voice}" || {
                log "WARNING: Piper voice download failed: ${voice}. TTS will fall back to pico if needed."
                continue
            }
    done
}

install_supertonic_model() {
    local supertonic_bin="${VENV_DIR}/bin/supertonic"

    if [ ! -x "${supertonic_bin}" ]; then
        log "WARNING: Supertonic CLI is not installed; skipping model pre-download."
        return 0
    fi

    mkdir -p "${SUPERTONIC_CACHE_DIR}" 2>/dev/null || true
    if [ "$(id -u)" -eq 0 ]; then
        sudo chown -R "${BYTERACER_USER}:${BYTERACER_USER}" "${SUPERTONIC_CACHE_DIR}" 2>/dev/null || true
    fi

    log "Pre-downloading Supertonic model into ${SUPERTONIC_CACHE_DIR}"
    run_as_app_user env SUPERTONIC_CACHE_DIR="${SUPERTONIC_CACHE_DIR}" \
        "${supertonic_bin}" download || {
            log "WARNING: Supertonic model download failed. Supertonic will retry on first use and fall back to pico if needed."
            return 0
        }
}

main() {
    local current_signature previous_signature dep

    prepare_venv || return 1
    current_signature="$(dependency_signature)"
    previous_signature="$(cat "${STAMP_FILE}" 2>/dev/null || true)"

    if [ "${FORCE_PYTHON_DEPS}" != "true" ] && [ "${current_signature}" = "${previous_signature}" ]; then
        if verify_python_stack >/dev/null 2>&1; then
            install_piper_voices
            install_supertonic_model
            log "ByteRacer Python venv is already in sync"
            return 0
        fi
        log "ByteRacer Python venv verification failed; reinstalling dependencies"
    fi

    pip_install --upgrade pip setuptools wheel || return 1

    log "Installing ByteRacer Python dependencies into venv"
    while IFS= read -r dep || [ -n "${dep}" ]; do
        dep="$(printf '%s' "${dep}" | sed -e 's/[[:space:]]*#.*$//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
        [ -n "${dep}" ] || continue
        install_requirement "${dep}" || {
            log "ERROR: Python dependency failed to install: ${dep}"
            return 1
        }
    done < "${REQUIREMENTS_FILE}"

    install_piper_voices
    install_supertonic_model

    log "Verifying ByteRacer Python venv"
    verify_python_stack || return 1
    printf '%s\n' "${current_signature}" | run_as_app_user tee "${STAMP_FILE}" >/dev/null
}

main "$@"
