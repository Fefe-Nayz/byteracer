#!/bin/bash
# Update script for ByteRacer with TTS feedback (hard reset)

# Project paths
BYTERACER_PATH="/home/pi/ByteRacer"
TTS_SCRIPT="${BYTERACER_PATH}/byteracer/tts/speak.py"
CONFIG_FILE="${BYTERACER_PATH}/byteracer/config/settings.json"
SCRIPTS_DIR="$(dirname "$0")"
LOG_FILE="${SCRIPTS_DIR}/update.log"

# Setup logging
exec > >(tee -a "${LOG_FILE}") 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ========== UPDATE STARTED =========="

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Function to run a command and log its output
run_cmd() {
    local cmd="$1"
    log "Executing: $cmd"
    output=$(eval "$cmd" 2>&1)
    exit_code=$?
    if [ -n "$output" ]; then
       echo "$output" | while IFS= read -r line; do
           log "  > $line"
       done
    fi
    log "Command exit code: $exit_code"
    return $exit_code
}

# Function to speak with TTS
speak() {
    if [ -f "$TTS_SCRIPT" ]; then
        python3 "$TTS_SCRIPT" "$1"
    else
        log "TTS script not found: $TTS_SCRIPT"
    fi
}

# Function to get a configuration value from the JSON config file
get_config() {
    local key=$1
    local default=$2
    
    if [ ! -f "$CONFIG_FILE" ]; then
        log "Config file not found: $CONFIG_FILE, using default: $default" >&2
        echo "$default"
        return
    fi
    
    if ! command -v jq &> /dev/null; then
        log "jq command not found, using default: $default" >&2
        echo "$default"
        return
    fi
    
    value=$(jq -r "$key" "$CONFIG_FILE" 2>/dev/null)
    result=$?
    
    if [ $result -ne 0 ] || [ "$value" = "null" ]; then
        log "Key $key not found in config or is null, using default: $default" >&2
        echo "$default"
    else
        log "Found configuration $key = $value" >&2
        echo "$value"
    fi
}

log "Updating ByteRacer components..."
speak "Checking for updates. Please wait."
speak "Starting update process for ByteRacer."

run_cmd "cd \"${BYTERACER_PATH}\""

BRANCH=$(get_config ".github.branch" "working-2")
REPO_URL=$(get_config ".github.repo_url" "https://github.com/nayzflux/byteracer.git")

log "Using GitHub Repository: $REPO_URL"
log "Using branch: $BRANCH"
speak "Using branch: $BRANCH for update."

log "Configuring Git safe directory..."
run_cmd "git config --global --add safe.directory \"${BYTERACER_PATH}\""

log "Checking for updates from GitHub branch: $BRANCH..."
speak "Checking for updates from GitHub branch $BRANCH."

run_cmd "git fetch origin"

# Capture commit hashes directly
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/$BRANCH)

log "Local commit hash: $LOCAL"
log "Remote commit hash: $REMOTE"

if [ "$LOCAL" = "$REMOTE" ]; then
    log "Already up to date. No update needed."
    speak "ByteRacer is already up to date on branch $BRANCH."
    log "========== UPDATE COMPLETED (No Updates) =========="
    exit 0
fi

log "Updates found on branch $BRANCH. Performing hard reset..."
speak "Updates found on branch $BRANCH. Downloading latest version."

# Perform a forced hard reset to update local branch to remote HEAD.
run_cmd "git reset --hard origin/$BRANCH"
GIT_STATUS=$?
if [ $GIT_STATUS -ne 0 ]; then
    log "Error: Failed to perform hard reset on branch $BRANCH (exit code $GIT_STATUS)"
    speak "Error updating branch $BRANCH. Update failed."
    log "========== UPDATE FAILED =========="
    exit 1
fi

log "Repository updated successfully. Listing changed files:"
run_cmd "git diff-tree --no-commit-id --name-status -r HEAD"

# Update relaytower (Bun webserver)
if [ -d "relaytower" ]; then
    log "[relaytower] Installing dependencies..."
    speak "Updating web server dependencies."
    run_cmd "cd relaytower && bun install"
    BUN_STATUS=$?
    if [ $BUN_STATUS -ne 0 ]; then
        log "Error: Failed to install relaytower dependencies (exit code $BUN_STATUS)"
    fi
    
    log "[relaytower] Building web server..."
    speak "Building web server."
    run_cmd "cd relaytower && bun run build"
    BUN_STATUS=$?
    if [ $BUN_STATUS -ne 0 ]; then
        log "Error: Failed to build relaytower (exit code $BUN_STATUS)"
    fi
else
    log "Warning: relaytower directory not found"
    run_cmd "ls -la"
fi

# Update eaglecontrol (WebSocket server)
if [ -d "eaglecontrol" ]; then
    log "[eaglecontrol] Installing dependencies..."
    speak "Updating WebSocket server dependencies."
    run_cmd "cd eaglecontrol && bun install"
    BUN_STATUS=$?
    if [ $BUN_STATUS -ne 0 ]; then
        log "Error: Failed to install eaglecontrol dependencies (exit code $BUN_STATUS)"
    fi
else
    log "Warning: eaglecontrol directory not found"
    run_cmd "ls -la"
fi

# Update byteracer Python dependencies
if [ -d "byteracer" ]; then
    run_cmd "cd byteracer"
    if [ -f "byteracer/requirements.txt" ]; then
        log "[byteracer] Installing Python dependencies..."
        speak "Updating Python dependencies."
        run_cmd "cd byteracer && cat requirements.txt"
        
        while IFS= read -r line || [ -n "$line" ]; do
            if [[ -z "$line" ]] || [[ "$line" =~ ^# ]]; then
                continue
            fi
            pkg=$(echo "$line" | cut -d'=' -f1)
            log "Installing python3-$pkg"
            run_cmd "sudo apt-get install -y python3-$pkg"
            APT_STATUS=$?
            if [ $APT_STATUS -ne 0 ]; then
                log "Error: Failed to install python3-$pkg (exit code $APT_STATUS)"
            fi
        done < byteracer/requirements.txt
    else
        log "Warning: requirements.txt not found"
        run_cmd "ls -la byteracer/"
    fi
    
    if [ -f "byteracer/install.sh" ]; then
        log "[byteracer] Running install script..."
        speak "Running additional installation steps."
        run_cmd "cd byteracer && sudo bash ./install.sh"
        INSTALL_STATUS=$?
        if [ $INSTALL_STATUS -ne 0 ]; then
            log "Error: install.sh failed (exit code $INSTALL_STATUS)"
        fi
    else
        log "Note: No install.sh script found"
        run_cmd "ls -la byteracer/"
    fi
else
    log "Warning: byteracer directory not found"
    run_cmd "ls -la"
fi

log "Update completed. Restarting services..."
speak "Update completed. Restarting all services to apply the changes."

log "Calling restart_services.sh"
run_cmd "sudo bash \"${BYTERACER_PATH}/byteracer/scripts/restart_services.sh\""
RESTART_STATUS=$?
if [ $RESTART_STATUS -ne 0 ]; then
    log "Error: restart_services.sh failed (exit code $RESTART_STATUS)"
    speak "Warning! Service restart failed. Some services may not be running."
else
    log "Services restarted successfully"
fi

log "Verifying running processes after restart:"
run_cmd "ps aux | grep -E 'python3 main.py|bun run .* eaglecontrol|bun run .* relaytower' | grep -v grep"

log "Update and restart complete."
speak "All updates have been installed and services restarted. ByteRacer is ready to use."

log "========== UPDATE COMPLETED =========="
