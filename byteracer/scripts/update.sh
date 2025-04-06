#!/bin/bash
# Update script for ByteRacer with TTS feedback

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
    # Execute the command and capture its output while logging it
    output=$(eval "$cmd" 2>&1)
    exit_code=$?
    
    # Log the command output with timestamp for each line
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

# Function to get a value from the config file
get_config() {
    local key=$1
    local default=$2
    
    # Check if the config file exists
    if [ ! -f "$CONFIG_FILE" ]; then
        log "Config file not found: $CONFIG_FILE, using default: $default"
        echo "$default"
        return
    fi
    
    # Check if jq is installed
    if ! command -v jq &> /dev/null; then
        log "jq command not found, using default: $default"
        echo "$default"
        return
    fi
    
    # Get the value from the config file
    value=$(jq -r "$key" "$CONFIG_FILE" 2>/dev/null)
    result=$?
    
    # Return the default value if the key doesn't exist or value is null
    if [ $result -ne 0 ] || [ "$value" = "null" ]; then
        log "Key $key not found in config or is null, using default: $default"
        echo "$default"
    else
        log "Found configuration $key = $value"
        echo "$value"
    fi
}

log "Updating ByteRacer components..."
speak "Checking for updates. Please wait."
speak "Starting update process for ByteRacer."

run_cmd "cd \"${BYTERACER_PATH}\""

# Get the branch from configuration
BRANCH=$(get_config ".github.branch" "working-2")
REPO_URL=$(get_config ".github.repo_url" "https://github.com/nayzflux/byteracer.git")

log "Using GitHub Repository: $REPO_URL"
log "Using branch: $BRANCH"
speak "Using branch: $BRANCH for update."

# Configure Git to handle directory ownership issues
log "Configuring Git safe directory..."
run_cmd "git config --global --add safe.directory \"${BYTERACER_PATH}\""

# Check for git updates
log "Checking for updates from GitHub branch: $BRANCH..."
speak "Checking for updates from GitHub branch $BRANCH."

run_cmd "git fetch origin"
LOCAL=$(run_cmd "git rev-parse HEAD" | tail -1)
REMOTE=$(run_cmd "git rev-parse origin/$BRANCH" | tail -1)

if [ "$LOCAL" = "$REMOTE" ]; then
    log "Already up to date. No update needed."
    speak "ByteRacer is already up to date on branch $BRANCH."
    log "========== UPDATE COMPLETED (No Updates) =========="
    exit 0
fi

# Updates found, pull changes
log "Updates found on branch $BRANCH. Pulling latest code..."
speak "Updates found on branch $BRANCH. Downloading latest version."

# Switch to the specified branch and pull changes
run_cmd "git checkout $BRANCH"
GIT_STATUS=$?
if [ $GIT_STATUS -ne 0 ]; then
    log "Error: Failed to checkout branch $BRANCH (exit code $GIT_STATUS)"
    speak "Error checking out branch $BRANCH. Update failed."
    log "========== UPDATE FAILED =========="
    exit 1
fi

run_cmd "git pull origin $BRANCH"
GIT_STATUS=$?
if [ $GIT_STATUS -ne 0 ]; then
    log "Error: Failed to pull from branch $BRANCH (exit code $GIT_STATUS)"
    speak "Error pulling updates from branch $BRANCH. Update failed."
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
        
        # Process each dependency in requirements.txt
        while IFS= read -r line || [ -n "$line" ]; do
            # Skip comments and empty lines
            if [[ -z "$line" ]] || [[ "$line" =~ ^# ]]; then
                continue
            fi
            # Remove any version specifiers
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

# Restart all services
log "Calling restart_services.sh"
run_cmd "sudo bash \"${BYTERACER_PATH}/byteracer/scripts/restart_services.sh\""
RESTART_STATUS=$?
if [ $RESTART_STATUS -ne 0 ]; then
    log "Error: restart_services.sh failed (exit code $RESTART_STATUS)"
    speak "Warning! Service restart failed. Some services may not be running."
else
    log "Services restarted successfully"
fi

# Verify running processes after restart
log "Verifying running processes after restart:"
run_cmd "ps aux | grep -E 'python3 main.py|bun run .* eaglecontrol|bun run .* relaytower' | grep -v grep"

log "Update and restart complete."
speak "All updates have been installed and services restarted. ByteRacer is ready to use."

log "========== UPDATE COMPLETED =========="