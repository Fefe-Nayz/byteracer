#!/bin/bash

set -uo pipefail

REPO_URL="${REPO_URL:-https://github.com/nayzflux/byteracer.git}"
BRANCH="${BRANCH:-working-2}"
TARGET_DIR="${TARGET_DIR:-/home/pi/ByteRacer}"
PI_USER="${PI_USER:-pi}"
INSTALL_ACCESSPOPUP="${INSTALL_ACCESSPOPUP:-false}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

run() {
    log "Executing: $*"
    "$@"
}

require_pi_user() {
    if ! id "${PI_USER}" >/dev/null 2>&1; then
        log "User ${PI_USER} does not exist"
        exit 1
    fi
}

install_apt_packages() {
    log "Installing system packages"
    sudo apt-get update
    sudo apt-get install -y \
        git curl ca-certificates jq screen sox libsox-fmt-all libttspico-utils \
        python3 python3-pip python3-dev python3-setuptools python3-wheel \
        python3-websockets python3-psutil python3-pygame python3-pyaudio \
        python3-numpy python3-pil portaudio19-dev \
        network-manager rfkill wireless-tools iw \
        zram-tools
}

install_bun() {
    if command -v bun >/dev/null 2>&1; then
        log "Bun already installed: $(bun --version)"
        return
    fi

    log "Installing Bun for ${PI_USER}"
    sudo -u "${PI_USER}" bash -lc 'curl -fsSL https://bun.sh/install | bash'
}

enable_pi_interfaces() {
    log "Enabling Raspberry Pi interfaces where raspi-config is available"
    if command -v raspi-config >/dev/null 2>&1; then
        sudo raspi-config nonint do_i2c 0 || true
        sudo raspi-config nonint do_ssh 0 || true
    fi
}

install_sunfounder_stack() {
    local base="/home/${PI_USER}/sunfounder-src"
    sudo -u "${PI_USER}" mkdir -p "${base}"

    if [ ! -d "${base}/robot-hat/.git" ]; then
        sudo -u "${PI_USER}" git clone -b v2.0 --depth=1 https://github.com/sunfounder/robot-hat.git "${base}/robot-hat"
    fi
    (cd "${base}/robot-hat" && run sudo python3 setup.py install)

    if [ ! -d "${base}/vilib/.git" ]; then
        sudo -u "${PI_USER}" git clone -b picamera2 --depth=1 https://github.com/sunfounder/vilib.git "${base}/vilib"
    fi
    (cd "${base}/vilib" && run sudo python3 install.py)

    if [ ! -d "${base}/picar-x/.git" ]; then
        sudo -u "${PI_USER}" git clone -b v2.0 --depth=1 https://github.com/sunfounder/picar-x.git "${base}/picar-x"
    fi
    (cd "${base}/picar-x" && run sudo python3 setup.py install)
}

install_accesspopup_if_requested() {
    if [ "${INSTALL_ACCESSPOPUP}" != "true" ]; then
        log "Skipping AccessPopup install. Set INSTALL_ACCESSPOPUP=true to install it."
        return
    fi

    if [ -x /usr/bin/accesspopup ]; then
        log "AccessPopup already installed"
        return
    fi

    local tmp="/tmp/AccessPopup"
    rm -rf "${tmp}" /tmp/AccessPopup.tar.gz
    curl -fsSL "https://www.raspberryconnect.com/images/scripts/AccessPopup.tar.gz" -o /tmp/AccessPopup.tar.gz
    tar -xzf /tmp/AccessPopup.tar.gz -C /tmp
    log "Run the AccessPopup installer manually if it prompts for interactive configuration: ${tmp}/installconfig.sh"
}

clone_app_only() {
    log "Installing app-only sparse checkout"
    sudo -u "${PI_USER}" env REPO_URL="${REPO_URL}" BRANCH="${BRANCH}" TARGET_DIR="${TARGET_DIR}" \
        bash "${TARGET_DIR}/byteracer/scripts/install_app_sparse.sh"
}

build_app() {
    log "Installing JS dependencies and building RelayTower"
    sudo -u "${PI_USER}" env PATH="/home/${PI_USER}/.bun/bin:${PATH}" bash -lc "cd '${TARGET_DIR}/relaytower' && bun install && bun run build"
    sudo -u "${PI_USER}" env PATH="/home/${PI_USER}/.bun/bin:${PATH}" bash -lc "cd '${TARGET_DIR}/eaglecontrol' && bun install"
}

configure_sd_protection() {
    log "Configuring SD-card-friendly defaults"

    sudo mkdir -p /etc/systemd/journald.conf.d
    sudo tee /etc/systemd/journald.conf.d/byteracer.conf >/dev/null <<'EOF'
[Journal]
Storage=volatile
RuntimeMaxUse=64M
SystemMaxUse=64M
EOF

    if awk '$2 == "/" && $4 !~ /(^|,)noatime(,|$)/ { found=1 } END { exit found ? 0 : 1 }' /etc/fstab; then
        sudo cp /etc/fstab "/etc/fstab.byteracer.$(date +%Y%m%d%H%M%S).bak"
        sudo sed -i -E 's#([[:space:]]/[[:space:]]+[^[:space:]]+[[:space:]]+)(defaults)([[:space:],])#\1defaults,noatime\3#' /etc/fstab || true
    fi

    if ! grep -qsE '^[^#]+\s+/tmp\s+tmpfs\s+' /etc/fstab; then
        echo "tmpfs /tmp tmpfs defaults,noatime,nosuid,nodev,size=256m 0 0" | sudo tee -a /etc/fstab >/dev/null
    fi

    if [ -f /etc/default/zramswap ]; then
        sudo sed -i -E 's/^#?PERCENT=.*/PERCENT=50/' /etc/default/zramswap || true
        sudo systemctl enable zramswap.service || true
    fi

    sudo systemctl restart systemd-journald || true
}

install_systemd_services() {
    log "Installing ByteRacer systemd services"
    sudo -u "${PI_USER}" env BYTERACER_PATH="${TARGET_DIR}" BYTERACER_USER="${PI_USER}" \
        bash "${TARGET_DIR}/byteracer/scripts/install_systemd_services.sh"
}

main() {
    require_pi_user
    install_apt_packages
    enable_pi_interfaces
    install_bun
    install_sunfounder_stack

    if [ ! -d "${TARGET_DIR}/.git" ]; then
        mkdir -p "$(dirname "${TARGET_DIR}")"
        sudo -u "${PI_USER}" git clone --filter=blob:none --depth=1 --sparse -b "${BRANCH}" "${REPO_URL}" "${TARGET_DIR}"
        sudo -u "${PI_USER}" git -C "${TARGET_DIR}" sparse-checkout set --no-cone \
            /byteracer/ /eaglecontrol/ /relaytower/ /startup.sh /README.md /.gitattributes /.gitignore
    else
        clone_app_only
    fi

    build_app
    configure_sd_protection
    install_systemd_services
    install_accesspopup_if_requested

    log "Bootstrap complete. Reboot is recommended before first production run."
    log "After reboot: sudo systemctl start byteracer-stack.target"
    log "Diagnostics: bash ${TARGET_DIR}/byteracer/scripts/doctor.sh"
}

main "$@"
