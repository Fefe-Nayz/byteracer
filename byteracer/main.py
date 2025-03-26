import time
import asyncio
import websockets
import json
import socket
import os
import subprocess
import threading
import psutil
from pathlib import Path

from vilib import Vilib
from picarx import Picarx

# Import the TTS (and optionally Music) from robot_hat
from robot_hat import Music, TTS, get_battery_voltage

SERVER_HOST = "127.0.0.1:3001"
PROJECT_DIR = Path(__file__).parent.parent  # Get ByteRacer root directory

px = Picarx()

# Global flag to stop speaking once a gamepad input arrives
stop_speaking_ip = False
# Track previous state of the "use" button
previous_use_state = False
# Global music instance
music_player = None
# Global camera state
camera_active = False

def get_ip():
    """
    Retrieves the IP address used by the Raspberry Pi.
    Falls back to '127.0.0.1' if unable to determine.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        # This address doesn't need to be reachable
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

async def speak_ip_periodically(tts):
    """
    Speaks the robot's IP address every 5 seconds until a gamepad input is received.
    """
    global stop_speaking_ip

    while not stop_speaking_ip:
        ip_address = get_ip()
        tts.say(f"My IP address is {ip_address}")
        await asyncio.sleep(5)

async def monitor_network_mode(tts):
    """
    Monitors the network mode by checking the IP address.
    If it detects a change (e.g., switching from Access Point mode to WiFi/Ethernet or vice-versa),
    it announces the new mode.
    """
    last_mode = None
    while True:
        ip_address = get_ip()
        # A simple check: if the IP starts with "127." we assume it's in AP (or fallback) mode.
        # Adjust this logic if your AP uses a different IP range.
        if ip_address.startswith("127."):
            current_mode = "Access Point mode"
        else:
            current_mode = "WiFi/Ethernet mode"
        
        if current_mode != last_mode:
            tts.say(f"Network mode changed: {current_mode}")
            if current_mode == "Access Point mode":
                tts.say("Please connect to the robot's WiFi hotspot and go to the adress 192.168.50.5:3000")
            else:
                tts.say(f"Please connet to the robot's same network and go to the adress {ip_address}:3000")
            print(f"Network mode changed: {current_mode}")
            last_mode = current_mode
        
        await asyncio.sleep(5)

def get_battery_level():
    """
    Get the battery voltage and calculate the percentage.
    From manufacturer's specs: "Battery Indicator
• Battery voltage above 7.8V will light up the two indicator LEDs. Battery voltage ranging from 6.7V to
7.8V will only light up one LED, voltage below 6.7V will turn both LEDs off."
    """

    # Get the battery voltage²
    voltage = get_battery_voltage()
    # Calculate the percentage based on the voltage
    # This is a simple linear approximation based on the specs
    # Adjust the ranges as per your battery specs
    if voltage >= 7.8:
        return 100
    elif voltage >= 6.7:
        return int((voltage - 6.7) / (7.8 - 6.7) * 100)
    else:
        return 0

def restart_camera_feed():
    """Restart the camera feed within the Python process"""
    global camera_active
    
    try:
        print("Restarting camera feed...")
        # Close the camera first if it's active
        Vilib.camera_close()
        time.sleep(1)  # Give it a moment to fully close
        
        # Restart the camera
        Vilib.camera_start(vflip=False, hflip=False)
        Vilib.display(local=False, web=True)
        camera_active = True
        print("Camera feed restarted successfully")
        return True
    except Exception as e:
        print(f"Error restarting camera feed: {e}")
        return False

def execute_system_command(cmd, success_msg):
    """Execute a system command and return success/failure"""
    try:
        print(f"Executing: {cmd}")
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        print(success_msg)
        print(f"Output: {result.stdout}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {e}")
        print(f"Error output: {e.stderr}")
        return False

async def execute_robot_command(command, websocket=None):
    """Handle different robot commands received from the debug interface"""
    result = {"success": False, "message": "Unknown command"}
    
    if command == "restart_robot":
        # Restart the entire system
        result = {"success": True, "message": "Rebooting system..."}
        if websocket:
            await websocket.send(json.dumps({
                "name": "command_response",
                "data": result,
                "createdAt": int(time.time() * 1000)
            }))
        # Schedule system reboot after brief delay to allow response to be sent
        threading.Timer(2.0, lambda: execute_system_command("sudo reboot", "System reboot initiated")).start()
        
    elif command == "stop_robot":
        # Shutdown the system
        result = {"success": True, "message": "Shutting down system..."}
        if websocket:
            await websocket.send(json.dumps({
                "name": "command_response",
                "data": result,
                "createdAt": int(time.time() * 1000)
            }))
        threading.Timer(2.0, lambda: execute_system_command("sudo shutdown -h now", "System shutdown initiated")).start()
        
    elif command == "restart_all_services":
        # Restart all three services
        result["success"] = execute_system_command(
            f"cd {PROJECT_DIR} && sudo bash ./scripts/restart_services.sh", 
            "All services restarted"
        )
        result["message"] = "All services restarted" if result["success"] else "Failed to restart services"
        
    elif command == "restart_websocket":
        # Restart just the WebSocket service
        result["success"] = execute_system_command(
            "screen -S eaglecontrol -X quit && cd /home/pi/ByteRacer/eaglecontrol && screen -dmS eaglecontrol bash -c 'bun run start; exec bash'", 
            "WebSocket service restarted"
        )
        result["message"] = "WebSocket service restarted" if result["success"] else "Failed to restart WebSocket service"
        
    elif command == "restart_web_server":
        # Restart just the web server
        result["success"] = execute_system_command(
            "screen -S relaytower -X quit && cd /home/pi/ByteRacer/relaytower && screen -dmS relaytower bash -c 'bun run start; exec bash'", 
            "Web server restarted"
        )
        result["message"] = "Web server restarted" if result["success"] else "Failed to restart web server"
        
    elif command == "restart_python_service":
        # Restart just the Python service
        result["success"] = True
        result["message"] = "Python service will restart"
        if websocket:
            await websocket.send(json.dumps({
                "name": "command_response",
                "data": result,
                "createdAt": int(time.time() * 1000)
            }))
        # Exit the Python script - systemd or screen will restart it
        threading.Timer(1.0, lambda: os._exit(0)).start()
        
    elif command == "restart_camera_feed":
        # Restart the camera feed within the Python process
        result["success"] = restart_camera_feed()
        result["message"] = "Camera feed restarted" if result["success"] else "Failed to restart camera feed"
        
    elif command == "check_for_updates":
        # Check for and apply updates
        result["success"] = execute_system_command(
            f"cd {PROJECT_DIR} && git fetch && if [ $(git rev-parse HEAD) != $(git rev-parse origin/main) ]; then git pull && sudo bash ./scripts/update.sh; else echo 'Already up to date'; fi", 
            "Update check completed"
        )
        result["message"] = "Update check completed" if result["success"] else "Failed to check for updates"
    
    # Return the result for handling by the calling function
    return result

def on_message(message, websocket=None):
    """
    Handles messages from the websocket.
    Stops the periodic IP announcements if a gamepad input is received.
    """
    global stop_speaking_ip, previous_use_state, music_player

    try:
        data = json.loads(message)
        if data["name"] == "welcome":
            print(f"Received welcome message, client ID: {data['data']['clientId']}")
        elif data["name"] == "gamepad_input":
            print(f"Received gamepad input: {data['data']}")
            stop_speaking_ip = True

            turn_value = float(data["data"].get("turn", 0))
            speed_value = float(data["data"].get("speed", 0))
            camera_pan_value = float(data["data"].get("turnCameraX", 0))
            camera_tilt_value = float(data["data"].get("turnCameraY", 0))
            use_value = data["data"].get("use", False)
            
            # Handle the "use" button with impulse triggering
            if use_value and not previous_use_state:
                print("Use button pressed - playing sound")
                if music_player:
                    # Play a sound - adjust filename as needed
                    music_player.sound_play_threading('assets/fart.mp3')
            
            # Update previous state
            previous_use_state = use_value
            
            px.set_motor_speed(1, speed_value * 100)  # normal motor
            px.set_motor_speed(2, speed_value * -100) # slow motor
            px.set_dir_servo_angle(turn_value * 30)
            px.set_cam_pan_angle(camera_pan_value * 90)
            if camera_tilt_value >= 0:
                px.set_cam_tilt_angle(camera_tilt_value * 65)
            else:
                px.set_cam_tilt_angle(camera_tilt_value * 35)
        
        elif data["name"] == "robot_command":
            # Handle robot commands from the debug interface
            command = data["data"].get("command")
            if command:
                print(f"Received robot command: {command}")
                # Use asyncio.create_task to avoid blocking the main message handler
                asyncio.create_task(handle_command(command, websocket))
                
        elif data["name"] == "battery_request":
            # Handle battery level request
            print("Received battery level request")
            battery_level = get_battery_level()
            if websocket:
                asyncio.create_task(send_battery_info(battery_level, websocket))
        
        else:
            print(f"Received message: {data['name']}")
    except json.JSONDecodeError:
        print(f"Received non-JSON message: {message}")
    except Exception as e:
        print(f"Error processing message: {e}")

async def handle_command(command, websocket):
    """Asynchronously handle robot commands"""
    try:
        result = await execute_robot_command(command, websocket)
        if websocket:
            await websocket.send(json.dumps({
                "name": "command_response",
                "data": result,
                "createdAt": int(time.time() * 1000)
            }))
    except Exception as e:
        print(f"Error executing command {command}: {e}")
        if websocket:
            await websocket.send(json.dumps({
                "name": "command_response",
                "data": {
                    "success": False,
                    "message": f"Error: {str(e)}"
                },
                "createdAt": int(time.time() * 1000)
            }))

async def send_battery_info(level, websocket):
    """Send battery level information back to the client"""
    try:
        await websocket.send(json.dumps({
            "name": "battery_info",
            "data": {
                "level": level,
                "timestamp": int(time.time() * 1000)
            },
            "createdAt": int(time.time() * 1000)
        }))
        print(f"Sent battery info: {level}%")
    except Exception as e:
        print(f"Error sending battery info: {e}")

async def connect_to_websocket(url):
    """
    Connects to the websocket server and listens for messages.
    Retries every 5 seconds on connection failure.
    """
    try:
        async with websockets.connect(url) as websocket:
            print(f"Connected to server at {url}!")
            # Register as a car
            register_message = json.dumps({
                "name": "client_register",
                "data": {
                    "type": "car",
                    "id": "byteracer-1"
                },
                "createdAt": int(time.time() * 1000)
            })
            await websocket.send(register_message)
            
            # Main message loop
            while True:
                try:
                    message = await websocket.recv()
                    # Pass the websocket to the message handler so it can respond
                    on_message(message, websocket)
                except websockets.exceptions.ConnectionClosed:
                    print("Connection closed")
                    break
                except Exception as e:
                    print(f"Error receiving message: {e}")
                    break
    except Exception as e:
        print(f"Connection error: {e}")
        print("Retrying in 5 seconds...")
        await asyncio.sleep(5)
        return await connect_to_websocket(url)

async def main():
    """
    Main entry point:
    - Starts the camera.
    - Initializes the TTS.
    - Launches three asynchronous tasks:
         1) Websocket connection.
         2) Periodically speaking the IP address.
         3) Monitoring network mode changes.
    """
    global music_player, camera_active
    
    # Start camera and display (local=False, web=True)
    Vilib.camera_start(vflip=False, hflip=False)
    Vilib.display(local=False, web=True)
    camera_active = True
    
    # Initialize TTS (set language if needed)
    tts = TTS()
    tts.lang("en-US")

    # Initialize Music (optional)
    music_player = Music()
    #music_player.music_play("assets/Ado.mp3")
    # Create necessary script directories and files
    setup_script_files()
    
    # Build URL with /ws route
    url = f"ws://{SERVER_HOST}/ws"
    print(f"Connecting to {url}...")
    
    # Run tasks concurrently:
    await asyncio.gather(
        connect_to_websocket(url),
        speak_ip_periodically(tts),
        monitor_network_mode(tts)
    )

def setup_script_files():
    """Set up necessary script files for command execution"""
    # Ensure scripts directory exists
    scripts_dir = PROJECT_DIR / 'scripts'
    scripts_dir.mkdir(exist_ok=True)
    
    # Create restart_services.sh
    restart_services_path = scripts_dir / 'restart_services.sh'
    if not restart_services_path.exists():
        with open(restart_services_path, 'w') as f:
            f.write('''#!/bin/bash
# Restart all three services
echo "Restarting all ByteRacer services..."

# Stop all services
screen -S eaglecontrol -X quit || true
screen -S relaytower -X quit || true
screen -S byteracer -X quit || true

sleep 2

# Start eaglecontrol service
cd /home/pi/ByteRacer/eaglecontrol
screen -dmS eaglecontrol bash -c "bun run start; exec bash"

# Start relaytower service
cd /home/pi/ByteRacer/relaytower
screen -dmS relaytower bash -c "bun run start; exec bash"

# Start byteracer service
cd /home/pi/ByteRacer/byteracer
screen -dmS byteracer bash -c "sudo python3 main.py; exec bash"

echo "All services have been restarted."
''')
    
    # Create update.sh
    update_script_path = scripts_dir / 'update.sh'
    if not update_script_path.exists():
        with open(update_script_path, 'w') as f:
            f.write('''#!/bin/bash
# Update script for ByteRacer
echo "Updating ByteRacer components..."

cd /home/pi/ByteRacer

# Update relaytower (Bun webserver)
if [ -d "relaytower" ]; then
    cd relaytower
    echo "[relaytower] Installing dependencies..."
    bun install
    echo "[relaytower] Building web server..."
    bun run build
    cd ..
fi

# Update eaglecontrol (WebSocket server)
if [ -d "eaglecontrol" ]; then
    cd eaglecontrol
    echo "[eaglecontrol] Installing dependencies..."
    bun install
    cd ..
fi

# Update byteracer Python dependencies
if [ -d "byteracer" ]; then
    cd byteracer
    if [ -f "requirements.txt" ]; then
        echo "[byteracer] Installing Python dependencies..."
        while IFS= read -r line || [ -n "$line" ]; do
            # Skip comments and empty lines
            if [[ -z "$line" ]] || [[ "$line" =~ ^# ]]; then
                continue
            fi
            # Remove any version specifiers
            pkg=$(echo "$line" | cut -d'=' -f1)
            echo "Installing python3-$pkg"
            sudo apt-get install -y python3-"$pkg"
        done < requirements.txt
    fi
    if [ -f "install.sh" ]; then
        echo "[byteracer] Running install script..."
        sudo bash ./install.sh
    fi
    cd ..
fi

echo "Update completed. Restarting services..."
sudo bash ./scripts/restart_services.sh
''')
    
    # Make the scripts executable
    os.chmod(restart_services_path, 0o755)
    os.chmod(update_script_path, 0o755)

if __name__ == "__main__":
    try:
        print("ByteRacer starting...")
        # Set up the necessary script files on startup
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
    finally:
        if camera_active:
            Vilib.camera_close()
        px.forward(0)
        px.set_dir_servo_angle(0)
        px.set_cam_pan_angle(0)
        px.set_cam_tilt_angle(0)
        print("ByteRacer offline.")



# TODO:
# - Add handling for other messages (e.g., camera fatures, microphone (speaker/ music etc), reboot/shutdown robot, restart services, check for updates, battery status, gamemodes, game specific commands, etc.)
# - Add error handling for camera and network issues
