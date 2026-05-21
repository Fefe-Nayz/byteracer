#!/bin/bash

set -uo pipefail

REPO_URL="${REPO_URL:-https://github.com/nayzflux/byteracer.git}"
BRANCH="${BRANCH:-working-2}"
TARGET_DIR="${TARGET_DIR:-/home/pi/ByteRacer}"
PI_USER="${PI_USER:-pi}"
INSTALL_ACCESSPOPUP="${INSTALL_ACCESSPOPUP:-true}"
ACCESSPOPUP_REPO="${ACCESSPOPUP_REPO:-https://github.com/RaspberryConnect/AccessPopup.git}"
ACCESSPOPUP_SSID="${ACCESSPOPUP_SSID:-ByteRacer}"
ACCESSPOPUP_PASSWORD="${ACCESSPOPUP_PASSWORD:-ByteRacerForever}"
ACCESSPOPUP_IP="${ACCESSPOPUP_IP:-192.168.50.5/24}"
ACCESSPOPUP_GATEWAY="${ACCESSPOPUP_GATEWAY:-192.168.50.254}"

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

run() {
    log "Executing: $*"
    "$@"
}

fail() {
    log "ERROR: $*"
    exit 1
}

run_required() {
    run "$@" || fail "Command failed: $*"
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
        git curl ca-certificates jq screen \
        raspi-config i2c-tools espeak sox libsox-fmt-all \
        libsdl2-dev libsdl2-mixer-dev \
        python3 python3-pip python3-dev python3-setuptools python3-wheel \
        python3-websockets python3-psutil python3-pygame python3-pyaudio \
        python3-numpy python3-pil portaudio19-dev \
        network-manager rfkill wireless-tools iw \
        dnsmasq-base zram-tools

    sudo apt-get install -y libttspico-utils || \
        log "libttspico-utils is unavailable from apt on this OS; SunFounder installer may install pico2wave another way"
}

install_bun() {
    local bun_bin="/home/${PI_USER}/.bun/bin/bun"

    if [ -x "${bun_bin}" ]; then
        log "Bun already installed: $(${bun_bin} --version)"
        return
    fi

    log "Installing Bun for ${PI_USER}"
    sudo -u "${PI_USER}" bash -lc 'curl -fsSL https://bun.sh/install | bash'
    [ -x "${bun_bin}" ] || fail "Bun installation did not create ${bun_bin}"
}

enable_pi_interfaces() {
    log "Enabling Raspberry Pi interfaces where raspi-config is available"
    if command -v raspi-config >/dev/null 2>&1; then
        sudo raspi-config nonint do_i2c 0 || true
        sudo raspi-config nonint do_spi 0 || true
        sudo raspi-config nonint do_ssh 0 || true
    fi
}

install_python_project() {
    local project_dir="$1"
    local project_name="$2"
    local break_system_packages=""

    if [ -f "${project_dir}/install.py" ]; then
        log "Installing ${project_name} through install.py"
        (cd "${project_dir}" && run sudo python3 install.py)
        return
    fi

    if pip3 help install 2>/dev/null | grep -q -- "--break-system-packages"; then
        break_system_packages="--break-system-packages"
    fi

    if [ -f "${project_dir}/pyproject.toml" ] || [ -f "${project_dir}/setup.py" ]; then
        log "Installing ${project_name} through pip"
        (cd "${project_dir}" && run sudo pip3 install ./ ${break_system_packages})
        return
    fi

    log "No install.py, pyproject.toml or setup.py found for ${project_name} in ${project_dir}"
    return 1
}

install_sunfounder_stack() {
    local base="/home/${PI_USER}/sunfounder-src"
    sudo -u "${PI_USER}" mkdir -p "${base}"

    if [ ! -d "${base}/robot-hat/.git" ]; then
        sudo -u "${PI_USER}" git clone -b v2.0 --depth=1 https://github.com/sunfounder/robot-hat.git "${base}/robot-hat"
    fi
    install_python_project "${base}/robot-hat" "robot-hat"

    if [ ! -d "${base}/vilib/.git" ]; then
        sudo -u "${PI_USER}" git clone -b picamera2 --depth=1 https://github.com/sunfounder/vilib.git "${base}/vilib"
    fi
    install_python_project "${base}/vilib" "vilib"

    if [ ! -d "${base}/picar-x/.git" ]; then
        sudo -u "${PI_USER}" git clone -b v2.0 --depth=1 https://github.com/sunfounder/picar-x.git "${base}/picar-x"
    fi
    install_python_project "${base}/picar-x" "picar-x"
}

install_accesspopup_if_requested() {
    if [ "${INSTALL_ACCESSPOPUP}" != "true" ]; then
        log "Skipping AccessPopup install. Set INSTALL_ACCESSPOPUP=true to install it."
        return
    fi

    local src="/home/${PI_USER}/sunfounder-src/AccessPopup"
    local wifi_interface="wlan0"

    if command -v iw >/dev/null 2>&1; then
        wifi_interface="$(iw dev 2>/dev/null | awk '$1 == "Interface" { print $2; exit }')"
        wifi_interface="${wifi_interface:-wlan0}"
    fi

    log "Installing AccessPopup for interface ${wifi_interface}"

    sudo apt-get install -y iw dnsmasq-base
    sudo systemctl enable --now NetworkManager.service || true

    if systemctl is-active --quiet hostapd.service; then
        log "Disabling hostapd because it conflicts with NetworkManager access points"
        sudo systemctl disable --now hostapd.service || true
    fi

    if systemctl is-enabled --quiet dnsmasq.service; then
        log "Disabling dnsmasq.service because AccessPopup uses dnsmasq-base through NetworkManager"
        sudo systemctl disable --now dnsmasq.service || true
    fi

    if [ ! -d "${src}/.git" ]; then
        sudo -u "${PI_USER}" git clone --depth=1 "${ACCESSPOPUP_REPO}" "${src}"
    else
        sudo -u "${PI_USER}" git -C "${src}" pull --ff-only || true
    fi

    [ -f "${src}/accesspopup" ] || fail "AccessPopup script not found in ${src}"
    [ -f "${src}/accesspopup.conf" ] || fail "AccessPopup config not found in ${src}"

    sudo install -m 0755 "${src}/accesspopup" /usr/local/bin/accesspopup
    if [ ! -f /etc/accesspopup.conf ]; then
        sudo install -m 0644 "${src}/accesspopup.conf" /etc/accesspopup.conf
    fi

    sudo sed -i \
        -e "s/^wdev0=.*/wdev0='${wifi_interface}'/" \
        -e "s/^ap_ssid=.*/ap_ssid='${ACCESSPOPUP_SSID}'/" \
        -e "s/^ap_pw=.*/ap_pw='${ACCESSPOPUP_PASSWORD}'/" \
        -e "s#^ap_ip=.*#ap_ip='${ACCESSPOPUP_IP}'#" \
        -e "s#^ap_gate=.*#ap_gate='${ACCESSPOPUP_GATEWAY}'#" \
        /etc/accesspopup.conf

    sudo tee /etc/systemd/system/AccessPopup.service >/dev/null <<'EOF'
[Unit]
Description=Automatically creates a NetworkManager access point when no known WiFi is available
After=NetworkManager.service network-online.target
Wants=NetworkManager.service network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/accesspopup

[Install]
WantedBy=multi-user.target
EOF

    sudo tee /etc/systemd/system/AccessPopup.timer >/dev/null <<'EOF'
[Unit]
Description=Run AccessPopup network checks every 2 minutes

[Timer]
OnBootSec=30s
OnUnitActiveSec=2min
Unit=AccessPopup.service

[Install]
WantedBy=timers.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable --now AccessPopup.timer
    sudo /usr/local/bin/accesspopup || log "AccessPopup first run failed; timer remains installed"
    log "AccessPopup installed. SSID=${ACCESSPOPUP_SSID}, IP=${ACCESSPOPUP_IP}"
}

clone_app_only() {
    log "Installing app-only sparse checkout"

    if [ -d "${TARGET_DIR}/.git" ]; then
        sudo -u "${PI_USER}" git -C "${TARGET_DIR}" remote set-url origin "${REPO_URL}" || \
            sudo -u "${PI_USER}" git -C "${TARGET_DIR}" remote add origin "${REPO_URL}" || return 1
        sudo -u "${PI_USER}" git -C "${TARGET_DIR}" fetch --depth=1 origin "${BRANCH}" || return 1
        sudo -u "${PI_USER}" git -C "${TARGET_DIR}" sparse-checkout init --no-cone || return 1
        sudo -u "${PI_USER}" git -C "${TARGET_DIR}" sparse-checkout set --no-cone "${APP_PATHS[@]}" || return 1
        sudo -u "${PI_USER}" git -C "${TARGET_DIR}" checkout -B "${BRANCH}" "origin/${BRANCH}" || return 1
        return 0
    fi

    if [ -e "${TARGET_DIR}" ]; then
        fail "${TARGET_DIR} already exists but is not a git checkout. Move it away before rerunning bootstrap."
    fi

    mkdir -p "$(dirname "${TARGET_DIR}")"
    sudo -u "${PI_USER}" git clone --filter=blob:none --depth=1 --sparse -b "${BRANCH}" "${REPO_URL}" "${TARGET_DIR}" || return 1
    sudo -u "${PI_USER}" git -C "${TARGET_DIR}" sparse-checkout set --no-cone "${APP_PATHS[@]}"
}

build_app() {
    local bun_bin="/home/${PI_USER}/.bun/bin/bun"

    [ -x "${bun_bin}" ] || fail "Bun executable not found at ${bun_bin}"

    log "Installing JS dependencies and building RelayTower"
    sudo -u "${PI_USER}" bash -c "cd '${TARGET_DIR}/relaytower' && '${bun_bin}' install && '${bun_bin}' run build" || return 1
    sudo -u "${PI_USER}" bash -c "cd '${TARGET_DIR}/eaglecontrol' && '${bun_bin}' install" || return 1
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
    [ -f "${TARGET_DIR}/byteracer/scripts/install_systemd_services.sh" ] || \
        fail "Missing ${TARGET_DIR}/byteracer/scripts/install_systemd_services.sh. Push the latest ByteRacer branch before running bootstrap."
    sudo -u "${PI_USER}" env BYTERACER_PATH="${TARGET_DIR}" BYTERACER_USER="${PI_USER}" \
        bash "${TARGET_DIR}/byteracer/scripts/install_systemd_services.sh"
}

verify_app_checkout() {
    local required_files=(
        "${TARGET_DIR}/startup.sh"
        "${TARGET_DIR}/byteracer/scripts/common.sh"
        "${TARGET_DIR}/byteracer/scripts/install_systemd_services.sh"
        "${TARGET_DIR}/relaytower/package.json"
        "${TARGET_DIR}/eaglecontrol/package.json"
    )

    for file in "${required_files[@]}"; do
        [ -f "${file}" ] || fail "Required application file is missing after checkout: ${file}"
    done
}

main() {
    require_pi_user
    install_apt_packages || fail "System package installation failed"
    enable_pi_interfaces || true
    install_bun
    install_sunfounder_stack || fail "SunFounder stack installation failed"

    clone_app_only || fail "Application sparse checkout update failed"

    verify_app_checkout
    build_app || fail "Application build failed"
    configure_sd_protection || fail "SD protection configuration failed"
    install_systemd_services || fail "Systemd service installation failed"
    install_accesspopup_if_requested || log "AccessPopup installation failed; continuing without AccessPopup"

    log "Bootstrap complete. Reboot is recommended before first production run."
    log "After reboot: sudo systemctl start byteracer-stack.target"
    log "Diagnostics: bash ${TARGET_DIR}/byteracer/scripts/doctor.sh"
}

main "$@"
