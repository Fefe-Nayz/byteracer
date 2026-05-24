#!/bin/bash

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export BYTERACER_PATH="${BYTERACER_PATH:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

LOCK_FILE="${BYTERACER_PATH}/byteracer/modules/custom-libs.lock.json"
MODULES_DIR="${BYTERACER_PATH}/byteracer/modules"
CUSTOM_BRANCH="${BYTERACER_CUSTOM_LIB_BRANCH:-byteracer-custom}"
PATCH_COMMIT_DATE="${BYTERACER_CUSTOM_LIB_COMMIT_DATE:-2026-05-24T00:00:00Z}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

read_lock_entries() {
    python3 - "${LOCK_FILE}" <<'PY'
import json
import sys
from pathlib import Path

lock_file = Path(sys.argv[1])
data = json.loads(lock_file.read_text())
for name, item in data.items():
    print("\t".join([
        name,
        item["repo"],
        item["branch"],
        item["commit"],
        item["target"],
        item.get("patch_dir", ""),
    ]))
PY
}

ensure_git_checkout() {
    local repo="$1"
    local branch="$2"
    local commit="$3"
    local target_dir="$4"
    local name="$5"

    if [ -e "${target_dir}" ] && [ ! -d "${target_dir}/.git" ]; then
        local backup="${target_dir}.legacy.$(date +%Y%m%d%H%M%S)"
        log "${name}: ${target_dir} exists but is not a git checkout; moving it to ${backup}"
        mv "${target_dir}" "${backup}" || return 1
    fi

    if [ ! -d "${target_dir}/.git" ]; then
        log "${name}: cloning ${repo}"
        git clone "${repo}" "${target_dir}" || return 1
    fi

    git -C "${target_dir}" remote set-url origin "${repo}" 2>/dev/null || \
        git -C "${target_dir}" remote add origin "${repo}" || return 1

    log "${name}: fetching ${branch}"
    git -C "${target_dir}" fetch --depth=50 origin "${branch}" || return 1

    if ! git -C "${target_dir}" cat-file -e "${commit}^{commit}" 2>/dev/null; then
        log "${name}: fetching pinned commit ${commit}"
        git -C "${target_dir}" fetch --depth=1 origin "${commit}" || return 1
    fi

    git -C "${target_dir}" checkout -B "${CUSTOM_BRANCH}" "${commit}" || return 1
    git -C "${target_dir}" reset --hard "${commit}" >/dev/null || return 1
    git -C "${target_dir}" clean -fdx >/dev/null || return 1
}

apply_patch_stack() {
    local target_dir="$1"
    local patch_dir="$2"
    local name="$3"
    local patch

    if [ -z "${patch_dir}" ] || [ ! -d "${patch_dir}" ]; then
        log "${name}: no ByteRacer patch directory configured"
        return 0
    fi

    while IFS= read -r patch; do
        [ -n "${patch}" ] || continue
        log "${name}: applying $(basename "${patch}")"
        git -C "${target_dir}" apply --ignore-space-change --whitespace=nowarn "${patch}" || \
            git -C "${target_dir}" apply --3way --ignore-space-change --whitespace=nowarn "${patch}" || return 1
    done < <(find "${patch_dir}" -maxdepth 1 -type f -name '*.patch' | sort)
}

commit_patch_stack() {
    local target_dir="$1"
    local name="$2"

    if [ -z "$(git -C "${target_dir}" status --porcelain)" ]; then
        log "${name}: no ByteRacer patch changes"
        return 0
    fi

    git -C "${target_dir}" add -A || return 1
    GIT_AUTHOR_DATE="${PATCH_COMMIT_DATE}" \
    GIT_COMMITTER_DATE="${PATCH_COMMIT_DATE}" \
        git -C "${target_dir}" \
            -c user.name="ByteRacer" \
            -c user.email="byteracer@example.invalid" \
            commit -m "Apply ByteRacer custom patches" >/dev/null || return 1
}

sync_one() {
    local name="$1"
    local repo="$2"
    local branch="$3"
    local commit="$4"
    local target="$5"
    local patch_dir="$6"
    local target_dir="${MODULES_DIR}/${target}"
    local patch_dir_abs=""

    if [ -n "${patch_dir}" ]; then
        patch_dir_abs="${MODULES_DIR}/${patch_dir}"
    fi

    ensure_git_checkout "${repo}" "${branch}" "${commit}" "${target_dir}" "${name}" || return 1
    apply_patch_stack "${target_dir}" "${patch_dir_abs}" "${name}" || return 1
    commit_patch_stack "${target_dir}" "${name}" || return 1

    log "${name}: ready at $(git -C "${target_dir}" rev-parse --short HEAD) (${target_dir})"
}

main() {
    [ -f "${LOCK_FILE}" ] || {
        log "Missing custom library lock file: ${LOCK_FILE}"
        return 1
    }

    while IFS=$'\t' read -r name repo branch commit target patch_dir; do
        [ -n "${name}" ] || continue
        sync_one "${name}" "${repo}" "${branch}" "${commit}" "${target}" "${patch_dir}" || return 1
    done < <(read_lock_entries)
}

main "$@"
