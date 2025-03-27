# Complete Implementation of ByteRacer Enhancements

I've prepared comprehensive code updates for all your requirements. Here are the complete implementations:

## 1. Updated Python Code (main.py)

```python
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
PYTHON_DIR = Path(__file__).parent  # Get the directory containing this script

px = Picarx()

# Global flag to stop speaking once a gamepad input arrives
stop_speaking_ip = False
# Track previous state of the "use" button
previous_use_state = False
# Global music instance
music_player = None
# Global camera state
camera_active = False
# Track previous speed and turning values for sound effects
previous_speed = 0
previous_turn = 0
# Last time a control message was received
last_control_message_time = time.time()
# Flag to enable/disable sound effects
sound_effects_enabled = True

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

# Non-blocking TTS function
async def tts_speak(tts, text):
    """Run TTS in a separate thread to avoid blocking other operations"""
    if not tts:
        return

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: tts.say(text))

async def speak_ip_periodically(tts):
    """
    Speaks the robot's IP address every 5 seconds until a gamepad input is received.
    Now using French language.
    """
    global stop_speaking_ip

    while not stop_speaking_ip:
        ip_address = get_ip()
        await tts_speak(tts, f"Mon adresse IP est {ip_address}")
        await asyncio.sleep(5)

async def monitor_network_mode(tts):
    """
    Monitors the network mode by checking the IP address.
    If it detects a change (e.g., switching from Access Point mode to WiFi/Ethernet or vice-versa),
    it announces the new mode in French.
    """
    last_mode = None
    while True:
        ip_address = get_ip()
        # A simple check: if the IP starts with "127." we assume it's in AP (or fallback) mode.
        # Adjust this logic if your AP uses a different IP range.
        if ip_address.startswith("127."):
            current_mode = "Mode point d'accès"
        else:
            current_mode = "Mode WiFi ou Ethernet"

        if current_mode != last_mode:
            await tts_speak(tts, f"Mode réseau changé: {current_mode}")
            if current_mode == "Mode point d'accès":
                await tts_speak(tts, "Veuillez vous connecter au point d'accès du robot et aller à l'adresse 192.168.50.5:3000")
            else:
                await tts_speak(tts, f"Veuillez vous connecter au même réseau que le robot et aller à l'adresse {ip_address}:3000")
            print(f"Network mode changed: {current_mode}")
            last_mode = current_mode

        await asyncio.sleep(5)

async def monitor_camera_status(websocket=None):
    """
    Continuously monitors camera status and automatically restarts if issues are detected.
    Notifies clients via WebSocket when camera issues are detected or resolved.
    """
    global camera_active
    while True:
        try:
            # Check if camera should be active but isn't running
            if camera_active and not Vilib.camera_is_running():
                print("Camera error detected, attempting restart...")
                restart_result = restart_camera_feed()

                # Notify clients about camera status
                if websocket:
                    await websocket.send(json.dumps({
                        "name": "camera_status",
                        "data": {
                            "status": "restarted" if restart_result else "error",
                            "message": "Caméra redémarrée avec succès" if restart_result
                                    else "Problème de caméra détecté - vérifiez la connexion",
                            "timestamp": int(time.time() * 1000)
                        },
                        "createdAt": int(time.time() * 1000)
                    }))
        except Exception as e:
            print(f"Error monitoring camera: {e}")

        await asyncio.sleep(10)  # Check every 10 seconds

async def monitor_connection_status():
    """
    Monitor control message frequency and stop robot if connection appears to be lost.
    Also plays a warning sound when connection is lost.
    """
    global last_control_message_time, music_player

    while True:
        current_time = time.time()
        # If no control messages for 3 seconds while the robot is moving, stop it
        time_since_last_message = current_time - last_control_message_time
        if time_since_last_message > 3 and (px.speed != 0 or px.dir_servo_angle != 0):
            print(f"No control messages for {time_since_last_message:.1f} seconds. Stopping robot for safety.")

            # Stop the robot
            px.set_motor_speed(1, 0)
            px.set_motor_speed(2, 0)
            px.set_dir_servo_angle(0)

            # Play a warning sound
            if music_player:
                music_player.sound_play_threading('assets/connection_lost.mp3')

        await asyncio.sleep(0.5)  # Check twice per second

def get_battery_level():
    """
    Get the battery voltage and calculate the percentage.
    From manufacturer's specs: "Battery Indicator
    • Battery voltage above 7.8V will light up the two indicator LEDs. Battery voltage ranging from 6.7V to
    7.8V will only light up one LED, voltage below 6.7V will turn both LEDs off."
    """
    # Get the battery voltage
    voltage = get_battery_voltage()
    # Calculate the percentage based on the voltage
    # This is a simple linear approximation based on the specs
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
        time.sleep(5)  # Give it a moment to fully close

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

# Driving sound effects
def play_driving_sounds(current_speed, previous_speed, current_turn, previous_turn):
    """Play appropriate driving sounds based on vehicle state changes"""
    if not music_player or not sound_effects_enabled:
        return

    # Acceleration sound
    if abs(current_speed) > abs(previous_speed) + 0.15:
        music_player.sound_play_threading('assets/accelerate.mp3')
    # Braking/deceleration sound
    elif abs(current_speed) < abs(previous_speed) - 0.15 and abs(previous_speed) > 0.2:
        music_player.sound_play_threading('assets/brake.mp3')

    # Drift sound for sharp turns
    if abs(current_turn) > 0.7 and abs(previous_turn) <= 0.5:
        music_player.sound_play_threading('assets/drift.mp3')

# WiFi Management Functions
def list_wifi_networks():
    """Scan and return available WiFi networks"""
    try:
        result = subprocess.run(['sudo', 'iwlist', 'wlan0', 'scan'],
                               capture_output=True, text=True)
        networks = []

        for line in result.stdout.split('\n'):
            if 'ESSID:' in line:
                ssid = line.split('ESSID:"')[1].split('"')[0]
                if ssid and ssid not in [n['ssid'] for n in networks]:
                    networks.append({'ssid': ssid})

        return networks
    except Exception as e:
        print(f"Error scanning WiFi networks: {e}")
        return []

def get_saved_networks():
    """Get list of saved WiFi networks"""
    try:
        with open('/etc/wpa_supplicant/wpa_supplicant.conf', 'r') as f:
            content = f.read()

        networks = []
        for block in content.split('network={'):
            if 'ssid=' in block:
                ssid = block.split('ssid="')[1].split('"')[0]
                networks.append({'ssid': ssid})

        return networks
    except Exception as e:
        print(f"Error getting saved networks: {e}")
        return []

def add_wifi_network(ssid, password):
    """Add a new WiFi network"""
    try:
        # Format the network configuration
        network_config = f'\nnetwork={{\n\tssid="{ssid}"\n\tpsk="{password}"\n\tkey_mgmt=WPA-PSK\n}}\n'

        # Add it to the config file
        with open('/etc/wpa_supplicant/wpa_supplicant.conf', 'a') as f:
            f.write(network_config)

        # Restart the networking service
        subprocess.run(['sudo', 'systemctl', 'restart', 'wpa_supplicant'], check=True)

        return {"success": True, "message": f"Réseau {ssid} ajouté"}
    except Exception as e:
        print(f"Error adding WiFi network: {e}")
        return {"success": False, "message": f"Échec de l'ajout du réseau: {str(e)}"}

def remove_wifi_network(ssid):
    """Remove a WiFi network from configuration"""
    try:
        # Read the current config
        with open('/etc/wpa_supplicant/wpa_supplicant.conf', 'r') as f:
            lines = f.readlines()

        # Find and remove the network block
        new_lines = []
        skip_lines = False
        for line in lines:
            if f'ssid="{ssid}"' in line:
                skip_lines = True
            elif skip_lines and '}' in line:
                skip_lines = False
                continue

            if not skip_lines:
                new_lines.append(line)

        # Write the updated config
        with open('/etc/wpa_supplicant/wpa_supplicant.conf', 'w') as f:
            f.writelines(new_lines)

        # Restart the networking service
        subprocess.run(['sudo', 'systemctl', 'restart', 'wpa_supplicant'], check=True)

        return {"success": True, "message": f"Réseau {ssid} supprimé"}
    except Exception as e:
        print(f"Error removing WiFi network: {e}")
        return {"success": False, "message": f"Échec de la suppression du réseau: {str(e)}"}

def switch_network_mode(mode):
    """Switch between Access Point and WiFi client mode"""
    try:
        if mode == "ap":
            # Switch to Access Point mode
            result = subprocess.run(['sudo', 'accesspopup', '-a'],
                                  check=True, capture_output=True)
        else:
            # Switch to WiFi client mode
            result = subprocess.run(['sudo', 'accesspopup'],
                                  check=True, capture_output=True)

        return {
            "success": True,
            "message": f"Basculé en mode {'point d\'accès' if mode == 'ap' else 'WiFi'}",
            "output": result.stdout.decode()
        }
    except Exception as e:
        print(f"Error switching network mode: {e}")
        return {"success": False, "message": f"Échec du changement de mode: {str(e)}"}

async def execute_robot_command(command, websocket=None, data=None):
    """Enhanced command handler with detailed status reporting"""
    result = {
        "success": False,
        "message": "Commande inconnue",
        "command": command,
        "status": "failed"
    }

    if command == "restart_robot":
        # Restart the entire system
        result = {
            "success": True,
            "message": "Redémarrage du système...",
            "command": command,
            "status": "in_progress"
        }

        if websocket:
            await websocket.send(json.dumps({
                "name": "command_response",
                "data": result,
                "createdAt": int(time.time() * 1000)
            }))

        # Schedule system reboot after brief delay to allow response to be sent
        threading.Timer(2.0, lambda: execute_system_command("sudo reboot", "System reboot initiated")).start()
        return result

    elif command == "stop_robot":
        # Shutdown the system
        result = {
            "success": True,
            "message": "Arrêt du système...",
            "command": command,
            "status": "in_progress"
        }

        if websocket:
            await websocket.send(json.dumps({
                "name": "command_response",
                "data": result,
                "createdAt": int(time.time() * 1000)
            }))

        threading.Timer(2.0, lambda: execute_system_command("sudo shutdown -h now", "System shutdown initiated")).start()
        return result

    elif command == "restart_all_services":
        # Restart all three services
        result["status"] = "in_progress"
        result["message"] = "Redémarrage de tous les services..."

        if websocket:
            await websocket.send(json.dumps({
                "name": "command_response",
                "data": result,
                "createdAt": int(time.time() * 1000)
            }))

        success = execute_system_command(
            f"cd {PYTHON_DIR} && sudo bash ./scripts/restart_services.sh",
            "All services restarted"
        )

        result["success"] = success
        result["status"] = "completed" if success else "failed"
        result["message"] = "Tous les services redémarrés" if success else "Échec du redémarrage des services"

    elif command == "restart_websocket":
        # Restart just the WebSocket service
        result["status"] = "in_progress"
        result["message"] = "Redémarrage du service WebSocket..."

        if websocket:
            await websocket.send(json.dumps({
                "name": "command_response",
                "data": result,
                "createdAt": int(time.time() * 1000)
            }))

        success = execute_system_command(
            "screen -S eaglecontrol -X quit && cd /home/pi/ByteRacer/eaglecontrol && screen -dmS eaglecontrol bash -c 'bun run start; exec bash'",
            "WebSocket service restarted"
        )

        result["success"] = success
        result["status"] = "completed" if success else "failed"
        result["message"] = "Service WebSocket redémarré" if success else "Échec du redémarrage du service WebSocket"

    elif command == "restart_web_server":
        # Restart just the web server
        result["status"] = "in_progress"
        result["message"] = "Redémarrage du serveur web..."

        if websocket:
            await websocket.send(json.dumps({
                "name": "command_response",
                "data": result,
                "createdAt": int(time.time() * 1000)
            }))

        success = execute_system_command(
            "screen -S relaytower -X quit && cd /home/pi/ByteRacer/relaytower && screen -dmS relaytower bash -c 'bun run start; exec bash'",
            "Web server restarted"
        )

        result["success"] = success
        result["status"] = "completed" if success else "failed"
        result["message"] = "Serveur web redémarré" if success else "Échec du redémarrage du serveur web"

    elif command == "restart_python_service":
        # Restart just the Python service
        result["success"] = True
        result["status"] = "in_progress"
        result["message"] = "Service Python en cours de redémarrage"

        if websocket:
            await websocket.send(json.dumps({
                "name": "command_response",
                "data": result,
                "createdAt": int(time.time() * 1000)
            }))

        # Exit the Python script - systemd or screen will restart it
        threading.Timer(1.0, lambda: os._exit(0)).start()
        return result

    elif command == "restart_camera_feed":
        # Restart the camera feed within the Python process
        result["message"] = "Redémarrage de la caméra..."
        result["status"] = "in_progress"

        # Send initial status
        if websocket:
            await websocket.send(json.dumps({
                "name": "command_response",
                "data": result,
                "createdAt": int(time.time() * 1000)
            }))

        # Attempt to restart camera
        restart_success = restart_camera_feed()
        result["success"] = restart_success
        result["status"] = "completed" if restart_success else "failed"
        result["message"] = "Caméra redémarrée avec succès" if restart_success else "Échec du redémarrage de la caméra"

    elif command == "check_for_updates":
        # Detailed update process with progress reporting
        result["status"] = "checking"
        result["message"] = "Vérification des mises à jour..."

        # Send initial status
        if websocket:
            await websocket.send(json.dumps({
                "name": "command_response",
                "data": result,
                "createdAt": int(time.time() * 1000)
            }))

        # Check if updates are available
        process = subprocess.Popen(
            f"cd {PYTHON_DIR.parent} && git fetch && git rev-list HEAD...origin/main --count",
            shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, stderr = process.communicate()

        update_count = stdout.decode().strip()
        if update_count == "0":
            # No updates available
            result["success"] = True
            result["status"] = "up_to_date"
            result["message"] = "Le système est à jour"
        else:
            # Updates available, start updating
            result["status"] = "updating"
            result["message"] = f"{update_count} mises à jour trouvées. Installation en cours..."

            # Send progress update
            if websocket:
                await websocket.send(json.dumps({
                    "name": "command_response",
                    "data": result,
                    "createdAt": int(time.time() * 1000)
                }))

            # Apply the updates
            update_success = execute_system_command(
                f"cd {PYTHON_DIR.parent} && git pull && cd {PYTHON_DIR} && sudo bash ./scripts/update.sh",
                "Mises à jour appliquées avec succès"
            )

            result["success"] = update_success
            result["status"] = "completed" if update_success else "failed"
            result["message"] = "Mises à jour installées avec succès" if update_success else "Échec de l'installation des mises à jour"

    # WiFi management commands
    elif command == "wifi_list_available":
        networks = list_wifi_networks()
        result = {
            "success": True,
            "message": f"Trouvé {len(networks)} réseaux",
            "command": command,
            "networks": networks,
            "status": "completed"
        }

    elif command == "wifi_list_saved":
        networks = get_saved_networks()
        result = {
            "success": True,
            "message": f"Trouvé {len(networks)} réseaux enregistrés",
            "command": command,
            "networks": networks,
            "status": "completed"
        }

    elif command == "wifi_add_network":
        if not data or "ssid" not in data or "password" not in data:
            result = {
                "success": False,
                "message": "Paramètres manquants: SSID et mot de passe requis",
                "command": command,
                "status": "failed"
            }
        else:
            add_result = add_wifi_network(data["ssid"], data["password"])
            result = {
                "success": add_result["success"],
                "message": add_result["message"],
                "command": command,
                "status": "completed" if add_result["success"] else "failed"
            }

    elif command == "wifi_remove_network":
        if not data or "ssid" not in data:
            result = {
                "success": False,
                "message": "Paramètre manquant: SSID requis",
                "command": command,
                "status": "failed"
            }
        else:
            remove_result = remove_wifi_network(data["ssid"])
            result = {
                "success": remove_result["success"],
                "message": remove_result["message"],
                "command": command,
                "status": "completed" if remove_result["success"] else "failed"
            }

    elif command == "wifi_switch_mode":
        if not data or "mode" not in data:
            result = {
                "success": False,
                "message": "Paramètre manquant: mode requis (ap or wifi)",
                "command": command,
                "status": "failed"
            }
        elif data["mode"] not in ["ap", "wifi"]:
            result = {
                "success": False,
                "message": "Mode invalide. Utilisez 'ap' ou 'wifi'",
                "command": command,
                "status": "failed"
            }
        else:
            switch_result = switch_network_mode(data["mode"])
            result = {
                "success": switch_result["success"],
                "message": switch_result["message"],
                "command": command,
                "status": "completed" if switch_result["success"] else "failed"
            }

    # Return the result for handling by the calling function
    return result

def on_message(message, websocket=None):
    """
    Handles messages from the websocket.
    Stops the periodic IP announcements if a gamepad input is received.
    Now with sound effects for driving actions.
    """
    global stop_speaking_ip, previous_use_state, music_player
    global last_control_message_time, previous_speed, previous_turn

    try:
        data = json.loads(message)
        if data["name"] == "welcome":
            print(f"Received welcome message, client ID: {data['data']['clientId']}")
        elif data["name"] == "gamepad_input":
            print(f"Received gamepad input: {data['data']}")
            stop_speaking_ip = True

            # Update last control message time for connection monitoring
            last_control_message_time = time.time()

            turn_value = float(data["data"].get("turn", 0))
            speed_value = float(data["data"].get("speed", 0))
            camera_pan_value = float(data["data"].get("turnCameraX", 0))
            camera_tilt_value = float(data["data"].get("turnCameraY", 0))
            use_value = data["data"].get("use", False)

            # Play appropriate sounds based on driving changes
            play_driving_sounds(speed_value, previous_speed, turn_value, previous_turn)

            # Handle the "use" button with impulse triggering
            if use_value and not previous_use_state:
                print("Use button pressed - playing sound")
                if music_player:
                    # Play a sound - adjust filename as needed
                    music_player.sound_play_threading('assets/horn.mp3')

            # Update previous states for next comparison
            previous_use_state = use_value
            previous_speed = speed_value
            previous_turn = turn_value

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
            command_data = data["data"].get("data", {})
            if command:
                print(f"Received robot command: {command}")
                # Use asyncio.create_task to avoid blocking the main message handler
                asyncio.create_task(handle_command(command, websocket, command_data))

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

async def handle_command(command, websocket, data=None):
    """Asynchronously handle robot commands"""
    try:
        result = await execute_robot_command(command, websocket, data)
        if websocket and "status" in result and result["status"] != "in_progress":
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
                    "message": f"Erreur: {str(e)}",
                    "command": command,
                    "status": "failed"
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
    global websocket_connection

    try:
        async with websockets.connect(url) as websocket:
            websocket_connection = websocket
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

            # Start camera monitoring with the websocket
            asyncio.create_task(monitor_camera_status(websocket))

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
    Enhanced main function with French TTS and improved startup sequence
    """
    global music_player, camera_active

    # Initialize TTS with French language
    tts = TTS()
    tts.lang("fr-FR")  # Changed from "en-US" to "fr-FR"

    # Improved startup sequence in French
    startup_messages = [
        "Bonjour, je suis ByteRacer",
        "Initialisation des systèmes en cours",
        "Démarrage de la caméra",
        "Connexion au serveur",
        "ByteRacer est prêt à rouler!"
    ]

    # Start camera
    camera_start_success = False
    try:
        Vilib.camera_start(vflip=False, hflip=False)
        Vilib.display(local=False, web=True)
        camera_active = True
        camera_start_success = True
    except Exception as e:
        print(f"Camera startup error: {e}")
        await tts_speak(tts, "Problème de démarrage de la caméra")

    # Initialize Music
    music_player = Music()

    # Speak welcome messages
    for message in startup_messages:
        await tts_speak(tts, message)
        await asyncio.sleep(0.5)  # Brief pause between messages

    # Build URL with /ws route
    url = f"ws://{SERVER_HOST}/ws"
    print(f"Connecting to {url}...")

    # Run tasks concurrently
    await asyncio.gather(
        connect_to_websocket(url),
        speak_ip_periodically(tts),
        monitor_network_mode(tts),
        monitor_connection_status()
    )

if __name__ == "__main__":
    try:
        print("ByteRacer starting...")
        # Initialize the websocket_connection global
        websocket_connection = None
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
```

## 2. Updated WebSocketStatus.tsx

```tsx
"use client";
import { useGamepadContext } from "@/contexts/GamepadContext";
import { useEffect, useRef, useState, useCallback } from "react";
import { Card } from "./ui/card";
import { trackWsMessage, trackWsConnection, logError } from "./DebugState";
import { ActionKey, ActionInfo } from "@/hooks/useGamepad";
import { AlertTriangle } from "lucide-react";

type GamepadStateValue = boolean | string | number;

export default function WebSocketStatus() {
  const {
    isActionActive,
    getAxisValueForAction,
    selectedGamepadId,
    mappings,
    ACTION_GROUPS,
    ACTIONS,
  } = useGamepadContext();

  // Store function references in refs to avoid dependency issues
  const functionsRef = useRef({
    isActionActive,
    getAxisValueForAction,
    ACTION_GROUPS,
    ACTIONS,
  });

  // Keep refs in sync with the latest functions
  useEffect(() => {
    functionsRef.current = {
      isActionActive,
      getAxisValueForAction,
      ACTION_GROUPS,
      ACTIONS,
    };
  }, [isActionActive, getAxisValueForAction, ACTION_GROUPS, ACTIONS]);

  const [status, setStatus] = useState<
    "connecting" | "connected" | "disconnected"
  >("connecting");
  const [pingTime, setPingTime] = useState<number | null>(null);
  const [socket, setSocket] = useState<WebSocket | null>(null);
  const [reconnectTrigger, setReconnectTrigger] = useState(0);
  const pingTimestampRef = useRef<number>(0);
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const [batteryLevel, setBatteryLevel] = useState<number | null>(null);
  const [customWsUrl, setCustomWsUrl] = useState<string | null>(null);
  const [customCameraUrl, setCustomCameraUrl] = useState<string | null>(null);
  const [cameraStatus, setCameraStatus] = useState<{
    status: "normal" | "restarted" | "error";
    message: string;
  }>({ status: "normal", message: "" });

  // Event listeners for debug controls
  useEffect(() => {
    const handleReconnect = () => {
      console.log("Reconnecting WebSocket...");
      if (socket) {
        if (
          socket.readyState === WebSocket.OPEN ||
          socket.readyState === WebSocket.CONNECTING
        ) {
          socket.close();
        }
      }
      setReconnectTrigger((prev) => prev + 1);
    };

    const handleSendPing = () => {
      if (socket && socket.readyState === WebSocket.OPEN) {
        const pingData = {
          name: "ping",
          data: {
            sentAt: Date.now(),
            debug: true,
          },
          createdAt: Date.now(),
        };
        socket.send(JSON.stringify(pingData));
        trackWsMessage("sent", pingData);
      } else {
        logError("Cannot send ping", {
          reason: "Socket not connected",
          readyState: socket?.readyState,
        });
      }
    };

    const handleClearWsLogs = () => {
      trackWsMessage("sent", null);
      trackWsMessage("received", null);
      setStatus((prev) => (prev === "connected" ? "connected" : prev));
    };

    window.addEventListener("debug:reconnect-ws", handleReconnect);
    window.addEventListener("debug:send-ping", handleSendPing);
    window.addEventListener("debug:clear-ws-logs", handleClearWsLogs);

    return () => {
      window.removeEventListener("debug:reconnect-ws", handleReconnect);
      window.removeEventListener("debug:send-ping", handleSendPing);
      window.removeEventListener("debug:clear-ws-logs", handleClearWsLogs);
    };
  }, [socket]);

  // Handle URL updates from settings
  useEffect(() => {
    const handleUrlUpdate = (e: CustomEvent) => {
      setCustomWsUrl(e.detail.wsUrl);
      setCustomCameraUrl(e.detail.cameraUrl);
      console.log("URL settings updated:", e.detail);
    };

    window.addEventListener(
      "debug:update-urls",
      handleUrlUpdate as EventListener
    );

    // Load saved URLs on initial render
    const savedWsUrl = localStorage.getItem("debug_ws_url");
    const savedCameraUrl = localStorage.getItem("debug_camera_url");

    if (savedWsUrl) setCustomWsUrl(savedWsUrl);
    if (savedCameraUrl) setCustomCameraUrl(savedCameraUrl);

    return () => {
      window.removeEventListener(
        "debug:update-urls",
        handleUrlUpdate as EventListener
      );
    };
  }, []);

  // Handle robot command events
  useEffect(() => {
    const handleCommand = (e: CustomEvent) => {
      const { command, data } = e.detail;
      if (socket && socket.readyState === WebSocket.OPEN) {
        const commandData = {
          name: "robot_command",
          data: {
            command,
            data: data || {},
            timestamp: Date.now(),
          },
          createdAt: Date.now(),
        };

        socket.send(JSON.stringify(commandData));
        trackWsMessage("sent", commandData);
        console.log(`Robot command sent: ${command}`, data || {});
      } else {
        logError("Cannot send robot command", {
          reason: "Socket not connected",
          command,
          readyState: socket?.readyState,
        });
      }
    };

    const handleBatteryRequest = () => {
      if (socket && socket.readyState === WebSocket.OPEN) {
        const batteryRequestData = {
          name: "battery_request",
          data: {
            timestamp: Date.now(),
          },
          createdAt: Date.now(),
        };

        socket.send(JSON.stringify(batteryRequestData));
        trackWsMessage("sent", batteryRequestData);
      } else {
        // If not connected, use dummy data
        const dummyLevel = Math.round(65 + Math.random() * 25);
        setBatteryLevel(dummyLevel);

        window.dispatchEvent(
          new CustomEvent("debug:battery-update", {
            detail: { level: dummyLevel },
          })
        );
      }
    };

    const handleTabChange = (e: CustomEvent) => {
      if (e.detail.tab === "settings") {
        handleBatteryRequest();
      }
    };

    window.addEventListener(
      "debug:send-robot-command",
      handleCommand as EventListener
    );
    window.addEventListener(
      "debug:request-battery",
      handleBatteryRequest as EventListener
    );
    window.addEventListener(
      "debug:tab-change",
      handleTabChange as EventListener
    );

    return () => {
      window.removeEventListener(
        "debug:send-robot-command",
        handleCommand as EventListener
      );
      window.removeEventListener(
        "debug:request-battery",
        handleBatteryRequest as EventListener
      );
      window.removeEventListener(
        "debug:tab-change",
        handleTabChange as EventListener
      );
    };
  }, [socket]);

  // WebSocket connection effect
  useEffect(() => {
    if (socket) {
      if (
        socket.readyState === WebSocket.OPEN ||
        socket.readyState === WebSocket.CONNECTING
      ) {
        socket.close();
      }
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current);
        pingIntervalRef.current = null;
      }
    }

    // Determine which WebSocket URL to use
    let wsUrl;
    if (customWsUrl && customWsUrl.trim() !== "") {
      wsUrl = customWsUrl;
    } else {
      const hostname = window.location.hostname;
      wsUrl = `ws://${hostname}:3001/ws`;
    }

    console.log(
      `Connecting to WebSocket at ${wsUrl} (attempt #${reconnectTrigger})...`
    );
    setStatus("connecting");

    // Connect to websocket using the determined URL
    const ws = new WebSocket(wsUrl);
    setSocket(ws);

    ws.onopen = () => {
      console.log("Connected to gamepad server");
      setStatus("connected");

      // Track connection for debug state
      trackWsConnection("connect");

      // Reset camera status when reconnecting
      setCameraStatus({ status: "normal", message: "" });

      // Register as controller
      const registerData = {
        name: "client_register",
        data: {
          type: "controller",
          id: `controller-${Math.random().toString(36).substring(2, 9)}`,
        },
        createdAt: Date.now(),
      };

      ws.send(JSON.stringify(registerData));

      // Track message for debug
      trackWsMessage("sent", registerData);

      // Only start ping loop after connection is established
      pingIntervalRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          const pingData = {
            name: "ping",
            data: {
              sentAt: Date.now(),
            },
            createdAt: Date.now(),
          };

          ws.send(JSON.stringify(pingData));

          // Track ping for debug
          trackWsMessage("sent", pingData);
        }
      }, 500);
    };

    ws.onclose = () => {
      console.log("Disconnected from gamepad server");
      setStatus("disconnected");

      // Track disconnection for debug state
      trackWsConnection("disconnect");

      // Clear ping interval if connection closes
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current);
        pingIntervalRef.current = null;
      }
    };

    ws.onerror = (error) => {
      console.error("WebSocket error:", error);
      setStatus("disconnected");

      // Log error for debug state
      logError("WebSocket connection error", {
        message: "Connection error",
        errorType: error.type,
      });
    };

    ws.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data);

        // Track received message for debug
        trackWsMessage("received", event);

        if (event.name === "pong") {
          // Calculate round-trip time in milliseconds
          const now = Date.now();
          const latency = now - event.data.sentAt;
          setPingTime(latency);
        } else if (event.name === "battery_info") {
          const level = event.data.level;
          setBatteryLevel(level);

          // Broadcast to other components
          window.dispatchEvent(
            new CustomEvent("debug:battery-update", {
              detail: { level },
            })
          );
        } else if (event.name === "camera_status") {
          // Handle camera status updates
          setCameraStatus({
            status: event.data.status,
            message: event.data.message,
          });

          // Broadcast camera status to other components
          window.dispatchEvent(
            new CustomEvent("debug:camera-status", {
              detail: {
                status: event.data.status,
                message: event.data.message,
              },
            })
          );
        } else if (event.name === "command_response") {
          // Broadcast command responses to other components
          window.dispatchEvent(
            new CustomEvent("debug:command-response", {
              detail: event.data,
            })
          );
        }
      } catch (e) {
        console.error("Error parsing websocket message:", e);
        logError("Error parsing WebSocket message", {
          error: e,
          rawMessage: message.data,
        });
      }
    };

    return () => {
      // Clean up when effect runs again or component unmounts
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current);
        pingIntervalRef.current = null;
      }
      if (
        ws.readyState === WebSocket.OPEN ||
        ws.readyState === WebSocket.CONNECTING
      ) {
        ws.close();
      }
    };
  }, [reconnectTrigger, customWsUrl]);

  // Compute gamepad state
  const computeGamepadState = useCallback(() => {
    const { isActionActive, getAxisValueForAction, ACTION_GROUPS, ACTIONS } =
      functionsRef.current;

    const gamepadState: Record<string, GamepadStateValue> = {};
    const processedActions = new Set<ActionKey>();

    // Process each action group to create a combined value
    ACTION_GROUPS.forEach((group) => {
      // Only process groups with exactly 2 opposing actions (like forward/backward)
      if (group.actions.length === 2) {
        const [action1, action2] = group.actions;

        // Get values for both actions in the group
        const value1 = getActionValue(action1);
        const value2 = getActionValue(action2);

        // Combine the values (positive - negative)
        gamepadState[group.key] = (value1 - value2).toFixed(2);

        // Mark these actions as processed
        processedActions.add(action1);
        processedActions.add(action2);
      } else {
        // For groups with different number of actions, process individually
        group.actions.forEach((action) => {
          processAction(action);
          processedActions.add(action);
        });
      }
    });

    // Now process any remaining actions that weren't part of a group
    ACTIONS.forEach((actionInfo: ActionInfo) => {
      if (!processedActions.has(actionInfo.key)) {
        processAction(actionInfo.key);
      }
    });

    // Function to process an individual action and add it to gamepadState
    function processAction(action: ActionKey) {
      const mapping = mappings[action];
      if (!mapping || mapping.index === -1) return;

      const actionInfo = ACTIONS.find((a: ActionInfo) => a.key === action);
      if (!actionInfo) return;

      // Handle actions based on their type
      if (
        actionInfo.type === "button" ||
        (actionInfo.type === "both" && mapping.type === "button")
      ) {
        // For button actions (or "both" mapped to button)
        gamepadState[action] = isActionActive(action);
      } else if (
        actionInfo.type === "axis" ||
        (actionInfo.type === "both" && mapping.type === "axis")
      ) {
        // For axis actions (or "both" mapped to axis)
        const value = getAxisValueForAction(action);
        if (value !== undefined) {
          gamepadState[action] = value.toFixed(2);
        }
      }
    }

    // Helper function to get normalized value for an action
    function getActionValue(action: ActionKey): number {
      const mapping = mappings[action];

      if (!mapping || mapping.index === -1) {
        return 0;
      }

      if (mapping.type === "button") {
        return isActionActive(action) ? 1 : 0;
      }

      if (mapping.type === "axis") {
        return getAxisValueForAction(action) ?? 0;
      }

      return 0;
    }

    return gamepadState;
  }, [mappings]);

  // Send gamepad state periodically
  useEffect(() => {
    // Only send data if connected to WebSocket AND have a selected gamepad
    if (!socket || status !== "connected" || !selectedGamepadId) return;

    const interval = setInterval(() => {
      // Check connection state before sending
      if (socket.readyState === WebSocket.OPEN) {
        pingTimestampRef.current = Date.now();

        // Get the comprehensive gamepad state
        const gamepadState = computeGamepadState();

        const message = {
          name: "gamepad_input",
          data: gamepadState,
          createdAt: pingTimestampRef.current,
        };

        socket.send(JSON.stringify(message));
        trackWsMessage("sent", message);
      }
    }, 50); // Send updates at 20 Hz

    return () => clearInterval(interval);
  }, [socket, status, selectedGamepadId, computeGamepadState]);

  // Expose camera status to other parts of the app
  useEffect(() => {
    // Update global state with camera status
    window.dispatchEvent(
      new CustomEvent("camera:status-change", {
        detail: cameraStatus,
      })
    );
  }, [cameraStatus]);

  return (
    <Card className="p-4">
      <div>
        <div className="flex items-center justify-between">
          <h3 className="font-bold">Server Connection</h3>
          <div className="flex items-center">
            <div
              className={`w-3 h-3 rounded-full mr-2 ${
                status === "connected"
                  ? "bg-green-500"
                  : status === "connecting"
                  ? "bg-yellow-500"
                  : "bg-red-500"
              }`}
            ></div>
            <span className="text-sm">
              {status === "connected"
                ? "Connected"
                : status === "connecting"
                ? "Connecting..."
                : "Disconnected"}
            </span>
          </div>
        </div>
        {pingTime !== null && (
          <p className="text-xs text-gray-500">Ping: {pingTime} ms</p>
        )}

        {/* Camera warning indicator */}
        {cameraStatus.status === "error" && (
          <div className="mt-2 p-2 bg-amber-100 dark:bg-amber-900/30 text-amber-800 dark:text-amber-200 rounded-md flex items-center">
            <AlertTriangle size={14} className="mr-2 flex-shrink-0" />
            <span className="text-xs">{cameraStatus.message}</span>
          </div>
        )}
      </div>
    </Card>
  );
}
```

# Enhanced Components for ByteRacer

Let me update the remaining components as requested with improved UI states, WiFi management, and camera notifications.

## 1. CameraFeed.tsx with Toast Notifications

```tsx
"use client";
import { useState, useEffect, useRef } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { RefreshCw, Maximize, X, AlertTriangle } from "lucide-react";
import { Button } from "./ui/button";

export default function CameraFeed() {
  const [streamUrl, setStreamUrl] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [key, setKey] = useState(Date.now());
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showControls, setShowControls] = useState(false);
  const [cameraWarning, setCameraWarning] = useState<string | null>(null);
  const [showWarning, setShowWarning] = useState(false);
  const controlsTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const warningTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const fullscreenContainerRef = useRef<HTMLDivElement>(null);

  // Check for custom camera URL in localStorage
  useEffect(() => {
    const customUrl = localStorage.getItem("debug_camera_url");
    if (customUrl && customUrl.trim() !== "") {
      setStreamUrl(customUrl);
    } else {
      // Use default URL
      const hostname = window.location.hostname;
      setStreamUrl(`http://${hostname}:9000/mjpg`);
    }
  }, []);

  // Listen for camera status messages from WebSocket
  useEffect(() => {
    const handleCameraStatus = (e: CustomEvent) => {
      const { status, message } = e.detail;

      if (status === "error" || status === "restarted") {
        setCameraWarning(message);
        setShowWarning(true);

        // Auto-hide warning after 5 seconds
        if (warningTimeoutRef.current) {
          clearTimeout(warningTimeoutRef.current);
        }

        warningTimeoutRef.current = setTimeout(() => {
          setShowWarning(false);
        }, 5000);

        // If camera was restarted, refresh the stream
        if (status === "restarted") {
          refreshStream();
        }
      }
    };

    window.addEventListener(
      "camera:status-update",
      handleCameraStatus as EventListener
    );

    return () => {
      window.removeEventListener(
        "camera:status-update",
        handleCameraStatus as EventListener
      );

      if (warningTimeoutRef.current) {
        clearTimeout(warningTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isFullscreen) {
        setIsFullscreen(false);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isFullscreen]);

  // Handle fullscreen change events
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };

    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () =>
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  // Handle mouse movement to show/hide controls in fullscreen mode
  useEffect(() => {
    if (!isFullscreen) return;

    const handleMouseMove = () => {
      setShowControls(true);

      if (controlsTimeoutRef.current) {
        clearTimeout(controlsTimeoutRef.current);
      }

      controlsTimeoutRef.current = setTimeout(() => {
        setShowControls(false);
      }, 3000);
    };

    window.addEventListener("mousemove", handleMouseMove);

    // Initial timeout
    handleMouseMove();

    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      if (controlsTimeoutRef.current) {
        clearTimeout(controlsTimeoutRef.current);
      }
    };
  }, [isFullscreen]);

  const refreshStream = () => {
    setIsLoading(true);
    setError(null);
    setKey(Date.now()); // Change key to force img reload
  };

  const handleImageLoad = () => {
    setIsLoading(false);
    setError(null);
  };

  const handleImageError = () => {
    setIsLoading(false);
    setError(
      "Unable to connect to camera stream. Check if the camera is online."
    );
  };

  const toggleFullscreen = () => {
    if (!isFullscreen) {
      if (fullscreenContainerRef.current && document.fullscreenEnabled) {
        fullscreenContainerRef.current.requestFullscreen().catch((err) => {
          console.error(
            `Error attempting to enable fullscreen: ${err.message}`
          );
        });
      }
    } else {
      if (document.fullscreenElement) {
        document.exitFullscreen().catch((err) => {
          console.error(`Error attempting to exit fullscreen: ${err.message}`);
        });
      }
    }
    setIsFullscreen(!isFullscreen);
  };

  // Toast notification component for camera warnings
  const WarningToast = () => {
    if (!showWarning || !cameraWarning) return null;

    return (
      <div className="absolute top-4 right-4 z-50 bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200 px-4 py-2 rounded-md shadow-lg flex items-center gap-2 max-w-xs animate-in slide-in-from-right">
        <AlertTriangle className="h-4 w-4 flex-shrink-0" />
        <span className="text-xs">{cameraWarning}</span>
        <button
          onClick={() => setShowWarning(false)}
          className="ml-2 text-yellow-800 dark:text-yellow-200 hover:text-yellow-900 dark:hover:text-yellow-100"
        >
          <X className="h-3 w-3" />
        </button>
      </div>
    );
  };

  if (isFullscreen) {
    return (
      <div ref={fullscreenContainerRef} className="fixed inset-0 z-50 bg-black">
        {/* Show warning toast in fullscreen mode */}
        <WarningToast />

        {/* Blurred background */}
        <div className="absolute inset-0 overflow-hidden">
          <img
            key={`bg-${key}`}
            src={streamUrl}
            alt=""
            className="w-full h-full object-cover scale-110"
            style={{
              filter: "blur(15px)",
              opacity: 0.7,
              transform: "scale(1.1)",
            }}
          />
        </div>

        {/* Main video feed */}
        <div className="absolute inset-0 flex items-center justify-center z-10">
          <img
            key={key}
            src={streamUrl}
            alt="Camera Feed"
            className="h-screen"
            onLoad={handleImageLoad}
            onError={handleImageError}
          />
        </div>

        {/* Loading indicator */}
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/30 z-20">
            <div className="animate-spin h-12 w-12 border-4 border-primary border-t-transparent rounded-full"></div>
          </div>
        )}

        {/* Error message */}
        {error && (
          <div className="absolute inset-0 flex flex-col items-center justify-center p-4 z-30 bg-black/70">
            <p className="mb-4 text-center max-w-md text-white">{error}</p>
            <Button onClick={refreshStream}>
              <RefreshCw className="h-4 w-4 mr-2" />
              Try Again
            </Button>
          </div>
        )}

        {/* Exit fullscreen button - visible only on mouse movement */}
        <div
          className={`absolute top-6 right-6 transition-opacity duration-300 z-50 ${
            showControls ? "opacity-100" : "opacity-0 pointer-events-none"
          }`}
        >
          <Button
            variant="secondary"
            size="icon"
            onClick={toggleFullscreen}
            className="h-10 w-10 rounded-full bg-white/50 hover:bg-white/70 backdrop-blur-sm"
          >
            <X className="h-5 w-5" />
          </Button>
        </div>
      </div>
    );
  }

  return (
    <Card className="overflow-hidden relative">
      {/* Show warning toast in normal mode */}
      <WarningToast />

      <CardHeader>
        <div className="flex justify-between items-center">
          <CardTitle className="text-lg">Camera Feed</CardTitle>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={toggleFullscreen}
              className="h-8 px-2"
            >
              <Maximize className="h-4 w-4 mr-1" />
              Fullscreen
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={refreshStream}
              className="h-8 px-2"
            >
              <RefreshCw className="h-4 w-4 mr-1" />
              Refresh
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="relative">
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-background z-20">
            <div className="animate-spin h-8 w-8 border-4 border-primary border-t-transparent rounded-full"></div>
          </div>
        )}

        <div className="relative rounded-md overflow-hidden aspect-[16/9]">
          {/* Error state - positioned over entire feed */}
          {error && (
            <div className="absolute inset-0 flex flex-col items-center justify-center p-4 z-30 rounded-md bg-background">
              <p className="mb-4 text-center max-w-md">{error}</p>
              <Button onClick={refreshStream}>
                <RefreshCw className="h-4 w-4 mr-2" />
                Try Again
              </Button>
            </div>
          )}

          {/* Blurred background version (full width) */}
          <div className="absolute inset-0 overflow-hidden">
            <img
              key={`bg-${key}`}
              src={streamUrl}
              alt=""
              className="w-full h-full object-cover scale-110"
              style={{
                filter: "blur(15px)",
                opacity: 0.7,
                transform: "scale(1.1)",
              }}
            />
            <div className="absolute inset-0"></div>
          </div>

          {/* Centered 4:3 aspect ratio version */}
          <div className="absolute inset-0 flex items-center justify-center z-10">
            <div className="relative aspect-[4/3] h-full">
              <img
                key={key}
                src={streamUrl}
                alt="Camera Feed"
                className="h-full w-auto object-contain"
                style={{ maxHeight: "100%", maxWidth: "100%" }}
                onLoad={handleImageLoad}
                onError={handleImageError}
              />
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
```

## 2. DebugState.tsx with Enhanced Button States and WiFi Management

```tsx
"use client";
// ... keep all existing imports ...
import {
  ChevronDown,
  Clock,
  Send,
  Download,
  Activity,
  Info,
  Settings,
  AlertCircle,
  Wrench,
  Battery,
  RefreshCw,
  PowerOff,
  RotateCw,
  Wifi,
  Server,
  Code,
  Camera,
  Save,
  Plus,
  Delete,
  PlusCircle,
  CheckCircle2,
  XCircle,
  WifiOff,
  Loader2,
} from "lucide-react";
import { Label } from "./ui/label";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "./ui/tooltip";
import { Separator } from "./ui/separator";

// ... keep all existing code and add/modify sections below ...

// Add these new interfaces for button states
interface CommandState {
  status:
    | "idle"
    | "loading"
    | "success"
    | "error"
    | "in_progress"
    | "checking"
    | "updating"
    | "up_to_date";
  message: string;
}

interface WiFiNetwork {
  ssid: string;
  connected?: boolean;
}

export default function DebugState() {
  // ... keep existing state ...
  const [commandStates, setCommandStates] = useState<
    Record<string, CommandState>
  >({});
  const [availableNetworks, setAvailableNetworks] = useState<WiFiNetwork[]>([]);
  const [savedNetworks, setSavedNetworks] = useState<WiFiNetwork[]>([]);
  const [isLoadingNetworks, setIsLoadingNetworks] = useState(false);
  const [selectedNetwork, setSelectedNetwork] = useState<string>("");
  const [wifiPassword, setWifiPassword] = useState<string>("");
  const [addingNetwork, setAddingNetwork] = useState(false);
  const [networkMode, setNetworkMode] = useState<"wifi" | "ap">("wifi");

  // ... keep existing useEffect hooks ...

  // Listen for command responses from the server
  useEffect(() => {
    if (!isClient) return;

    const handleCommandResponse = (e: CustomEvent) => {
      const { command, status, message, success } = e.detail;

      setCommandStates((prev) => ({
        ...prev,
        [command]: {
          status: status || (success ? "success" : "error"),
          message: message || (success ? "Success" : "Failed"),
        },
      }));

      // Auto-clear success/error states after 3 seconds
      if (
        status === "success" ||
        status === "error" ||
        status === "completed" ||
        status === "failed" ||
        status === "up_to_date"
      ) {
        setTimeout(() => {
          setCommandStates((prev) => ({
            ...prev,
            [command]: { ...prev[command], status: "idle" },
          }));
        }, 3000);
      }

      // For network-related commands, refresh the network lists
      if (command === "wifi_list_available" && success) {
        setAvailableNetworks(e.detail.networks || []);
        setIsLoadingNetworks(false);
      } else if (command === "wifi_list_saved" && success) {
        setSavedNetworks(e.detail.networks || []);
      } else if (command === "wifi_switch_mode" && success) {
        setNetworkMode(e.detail.mode === "ap" ? "ap" : "wifi");
      }
    };

    const handleCameraStatus = (e: CustomEvent) => {
      const { status, message } = e.detail;
      // Update camera restart button status
      setCommandStates((prev) => ({
        ...prev,
        restart_camera_feed: {
          status: status === "restarted" ? "success" : "error",
          message: message,
        },
      }));
    };

    window.addEventListener(
      "command:response",
      handleCommandResponse as EventListener
    );

    window.addEventListener(
      "camera:status-update",
      handleCameraStatus as EventListener
    );

    return () => {
      window.removeEventListener(
        "command:response",
        handleCommandResponse as EventListener
      );
      window.removeEventListener(
        "camera:status-update",
        handleCameraStatus as EventListener
      );
    };
  }, [isClient]);

  // Function to send robot commands with data
  const sendRobotCommand = (command: string, data?: any) => {
    // Set the button to loading state
    setCommandStates((prev) => ({
      ...prev,
      [command]: { status: "loading", message: "Processing..." },
    }));

    window.dispatchEvent(
      new CustomEvent("debug:send-robot-command", {
        detail: { command, data },
      })
    );
  };

  // Function to scan for WiFi networks
  const scanWifiNetworks = () => {
    setIsLoadingNetworks(true);
    sendRobotCommand("wifi_list_available");
  };

  // Function to get saved WiFi networks
  const getSavedNetworks = () => {
    sendRobotCommand("wifi_list_saved");
  };

  // Function to add a WiFi network
  const addWifiNetwork = () => {
    if (!selectedNetwork && !addingNetwork) return;

    const ssid = addingNetwork ? selectedNetwork : wifiPassword;
    if (!ssid || !wifiPassword) return;

    sendRobotCommand("wifi_add_network", {
      ssid,
      password: wifiPassword,
    });

    // Reset form
    setSelectedNetwork("");
    setWifiPassword("");
    setAddingNetwork(false);
  };

  // Function to remove a WiFi network
  const removeWifiNetwork = (ssid: string) => {
    sendRobotCommand("wifi_remove_network", { ssid });
  };

  // Function to switch network mode
  const switchNetworkMode = (mode: "ap" | "wifi") => {
    sendRobotCommand("wifi_switch_mode", { mode });
  };

  // Helper function to render a button with appropriate state
  const CommandButton = ({
    command,
    icon,
    label,
    onClick,
    className = "",
  }: {
    command: string;
    icon: React.ReactNode;
    label: string;
    onClick: () => void;
    className?: string;
  }) => {
    const state = commandStates[command] || { status: "idle", message: "" };

    let buttonContent;
    let buttonVariant: "outline" | "destructive" | "default" = "outline";
    let isDisabled = false;

    switch (state.status) {
      case "loading":
      case "in_progress":
      case "checking":
      case "updating":
        buttonContent = (
          <>
            <Loader2 size={14} className="mr-2 animate-spin" />
            {state.status === "checking"
              ? "Checking..."
              : state.status === "updating"
              ? "Updating..."
              : "Loading..."}
          </>
        );
        isDisabled = true;
        break;
      case "success":
      case "completed":
      case "up_to_date":
        buttonContent = (
          <>
            <CheckCircle2 size={14} className="mr-2 text-green-500" />
            {label}
          </>
        );
        break;
      case "error":
      case "failed":
        buttonContent = (
          <>
            <XCircle size={14} className="mr-2 text-red-500" />
            {label}
          </>
        );
        buttonVariant = "destructive";
        break;
      default:
        buttonContent = (
          <>
            {icon}
            {label}
          </>
        );
    }

    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant={buttonVariant}
              size="sm"
              className={`text-xs h-7 px-2 flex items-center ${className}`}
              onClick={onClick}
              disabled={isDisabled}
            >
              {buttonContent}
            </Button>
          </TooltipTrigger>
          {state.message && (
            <TooltipContent>
              <p>{state.message}</p>
            </TooltipContent>
          )}
        </Tooltip>
      </TooltipProvider>
    );
  };

  // Prevent rendering on server
  if (!isClient) return null;

  // ... keep formatTime and other helper functions ...

  return (
    <Card className="my-4">
      {/* ... keep header ... */}
      <CardContent className="text-xs font-mono">
        <Tabs defaultValue="status" onValueChange={handleTabChange}>
          {/* ... keep existing tab list ... */}
          <TabsList className="mb-4">
            {/* ... keep existing tabs ... */}
            <TabsTrigger value="wifi" className="text-xs">
              <Wifi size={14} className="mr-1" /> WiFi
            </TabsTrigger>
          </TabsList>

          {/* ... keep existing tab content ... */}

          {/* Add WiFi Management Tab */}
          <TabsContent value="wifi">
            <div className="space-y-4">
              <div className="font-medium flex items-center">
                <Wifi size={16} className="mr-2" /> WiFi Management
              </div>
              <div className="text-muted-foreground text-xs mb-2">
                Manage the robot&apos;s wireless connections
              </div>

              {/* Network Mode Selection */}
              <div className="space-y-2">
                <div className="font-medium text-xs">Network Mode</div>
                <div className="flex gap-2">
                  <CommandButton
                    command="wifi_switch_mode_wifi"
                    icon={<Wifi size={14} className="mr-2" />}
                    label="WiFi Client Mode"
                    onClick={() => switchNetworkMode("wifi")}
                    className={networkMode === "wifi" ? "bg-primary/20" : ""}
                  />
                  <CommandButton
                    command="wifi_switch_mode_ap"
                    icon={<WifiOff size={14} className="mr-2" />}
                    label="Access Point Mode"
                    onClick={() => switchNetworkMode("ap")}
                    className={networkMode === "ap" ? "bg-primary/20" : ""}
                  />
                </div>
              </div>

              <Separator />

              {/* Available Networks */}
              <div className="space-y-2">
                <div className="flex justify-between items-center">
                  <div className="font-medium text-xs">Available Networks</div>
                  <CommandButton
                    command="wifi_list_available"
                    icon={<RefreshCw size={14} className="mr-2" />}
                    label="Scan"
                    onClick={scanWifiNetworks}
                  />
                </div>

                <div className="bg-muted p-2 rounded-md max-h-40 overflow-y-auto">
                  {isLoadingNetworks ? (
                    <div className="flex items-center justify-center py-4">
                      <Loader2 className="h-4 w-4 animate-spin mr-2" />
                      <span>Scanning networks...</span>
                    </div>
                  ) : availableNetworks.length === 0 ? (
                    <div className="text-center py-2 text-muted-foreground">
                      No networks found
                    </div>
                  ) : (
                    <ul className="space-y-1">
                      {availableNetworks.map((network, idx) => (
                        <li
                          key={idx}
                          className="flex items-center justify-between"
                        >
                          <div className="flex items-center">
                            <Wifi size={12} className="mr-2" />
                            {network.ssid}
                          </div>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 px-2"
                            onClick={() => {
                              setSelectedNetwork(network.ssid);
                              setAddingNetwork(false);
                            }}
                          >
                            <PlusCircle size={12} />
                          </Button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>

              {/* Saved Networks */}
              <div className="space-y-2">
                <div className="flex justify-between items-center">
                  <div className="font-medium text-xs">Saved Networks</div>
                  <CommandButton
                    command="wifi_list_saved"
                    icon={<RefreshCw size={14} className="mr-2" />}
                    label="Refresh"
                    onClick={getSavedNetworks}
                  />
                </div>

                <div className="bg-muted p-2 rounded-md max-h-40 overflow-y-auto">
                  {savedNetworks.length === 0 ? (
                    <div className="text-center py-2 text-muted-foreground">
                      No saved networks
                    </div>
                  ) : (
                    <ul className="space-y-1">
                      {savedNetworks.map((network, idx) => (
                        <li
                          key={idx}
                          className="flex items-center justify-between"
                        >
                          <div className="flex items-center">
                            <Wifi size={12} className="mr-2" />
                            {network.ssid}
                          </div>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 px-2 text-destructive"
                            onClick={() => removeWifiNetwork(network.ssid)}
                          >
                            <Delete size={12} />
                          </Button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>

              {/* Add Network Form */}
              <div className="space-y-2">
                <div className="font-medium text-xs">
                  {selectedNetwork
                    ? `Connect to "${selectedNetwork}"`
                    : "Add Network Manually"}
                </div>

                {!selectedNetwork && (
                  <div className="space-y-1">
                    <Label htmlFor="ssid" className="text-xs">
                      Network Name (SSID)
                    </Label>
                    <Input
                      id="ssid"
                      value={addingNetwork ? selectedNetwork : ""}
                      onChange={(e) => setSelectedNetwork(e.target.value)}
                      placeholder="Enter network name"
                      className="h-8 text-xs"
                    />
                  </div>
                )}

                <div className="space-y-1">
                  <Label htmlFor="password" className="text-xs">
                    Password
                  </Label>
                  <Input
                    id="password"
                    type="password"
                    value={wifiPassword}
                    onChange={(e) => setWifiPassword(e.target.value)}
                    placeholder="Enter network password"
                    className="h-8 text-xs"
                  />
                </div>

                <div className="flex gap-2">
                  <CommandButton
                    command="wifi_add_network"
                    icon={<Plus size={14} className="mr-2" />}
                    label="Add Network"
                    onClick={addWifiNetwork}
                  />

                  {selectedNetwork && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="text-xs h-7 px-2"
                      onClick={() => {
                        setSelectedNetwork("");
                        setWifiPassword("");
                      }}
                    >
                      Cancel
                    </Button>
                  )}
                </div>
              </div>
            </div>
          </TabsContent>

          {/* Update the Settings TabContent to use the new CommandButton component */}
          <TabsContent value="settings">
            <div className="space-y-4">
              <div className="font-medium flex items-center">
                <Wrench size={16} className="mr-2" /> Robot Management
              </div>
              <div className="text-muted-foreground text-xs mb-2">
                Control the robot&apos;s services and hardware
              </div>
              <div className="grid grid-cols-2 gap-4">
                <CommandButton
                  command="restart_robot"
                  icon={<RotateCw size={14} className="mr-2" />}
                  label="Restart Robot"
                  onClick={() => sendRobotCommand("restart_robot")}
                />
                <CommandButton
                  command="stop_robot"
                  icon={<PowerOff size={14} className="mr-2" />}
                  label="Stop Robot"
                  onClick={() => sendRobotCommand("stop_robot")}
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <CommandButton
                  command="restart_all_services"
                  icon={<RefreshCw size={14} className="mr-2" />}
                  label="Restart All Services"
                  onClick={() => sendRobotCommand("restart_all_services")}
                />
                <CommandButton
                  command="restart_websocket"
                  icon={<Wifi size={14} className="mr-2" />}
                  label="Restart WebSocket"
                  onClick={() => sendRobotCommand("restart_websocket")}
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <CommandButton
                  command="restart_web_server"
                  icon={<Server size={14} className="mr-2" />}
                  label="Restart Web Server"
                  onClick={() => sendRobotCommand("restart_web_server")}
                />
                <CommandButton
                  command="restart_python_service"
                  icon={<Code size={14} className="mr-2" />}
                  label="Restart Python Service"
                  onClick={() => sendRobotCommand("restart_python_service")}
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <CommandButton
                  command="restart_camera_feed"
                  icon={<Camera size={14} className="mr-2" />}
                  label="Restart Camera Feed"
                  onClick={() => sendRobotCommand("restart_camera_feed")}
                />
              </div>

              <div className="font-medium flex items-center mt-4">
                <Download size={16} className="mr-2" /> Software Management
              </div>
              <div className="text-muted-foreground text-xs mb-2">
                Manage the robot&apos;s software
              </div>
              <div className="grid grid-cols-2 gap-4">
                <CommandButton
                  command="check_for_updates"
                  icon={<Download size={14} className="mr-2" />}
                  label="Check for Updates"
                  onClick={() => sendRobotCommand("check_for_updates")}
                />
                <div className="flex items-center">
                  <Battery
                    size={16}
                    className="mr-2"
                    style={{
                      color:
                        batteryLevel === null
                          ? "var(--muted-foreground)"
                          : batteryLevel > 20
                          ? "var(--primary)"
                          : "var(--destructive)",
                    }}
                  />
                  <span className="text-muted-foreground text-xs">
                    Battery:{" "}
                    {batteryLevel === null ? "Unknown" : `${batteryLevel}%`}
                  </span>
                </div>
              </div>

              {/* ... keep connection settings section ... */}
            </div>
          </TabsContent>

          {/* ... keep other tab content ... */}
        </Tabs>

        {/* ... keep footer ... */}
      </CardContent>
    </Card>
  );
}
```

## 3. Updated Python `monitor_network_mode` Function

```python
async def monitor_network_mode(tts):
    """
    Monitors the network mode by checking the IP address.
    If it detects a change, it announces the new mode and restarts the camera if needed.
    """
    global camera_active, websocket_connection

    last_ip = None
    last_mode = None

    while True:
        ip_address = get_ip()
        network_changed = ip_address != last_ip

        # Determine network mode
        if ip_address.startswith("127."):
            current_mode = "Mode point d'accès"
        else:
            current_mode = "Mode WiFi ou Ethernet"

        # Check if network mode or IP has changed
        if current_mode != last_mode or network_changed:
            print(f"Network change detected: {last_ip} -> {ip_address}")

            # Announce the change
            await tts_speak(tts, f"Mode réseau changé: {current_mode}")
            if current_mode == "Mode point d'accès":
                await tts_speak(tts, "Veuillez vous connecter au point d'accès du robot et aller à l'adresse 192.168.50.5:3000")
            else:
                await tts_speak(tts, f"Veuillez vous connecter au même réseau que le robot et aller à l'adresse {ip_address}:3000")

            # Restart camera when network changes
            if network_changed and camera_active:
                print("Network changed, restarting camera...")
                restart_result = restart_camera_feed()

                # Notify via websocket if available
                if websocket_connection and hasattr(websocket_connection, 'send'):
                    try:
                        await websocket_connection.send(json.dumps({
                            "name": "camera_status",
                            "data": {
                                "status": "restarted" if restart_result else "error",
                                "message": "Caméra redémarrée après changement de réseau" if restart_result
                                        else "Problème de caméra après changement de réseau",
                                "timestamp": int(time.time() * 1000)
                            },
                            "createdAt": int(time.time() * 1000)
                        }))
                    except Exception as e:
                        print(f"Error sending camera status: {e}")

            # Update last known values
            last_mode = current_mode
            last_ip = ip_address

        await asyncio.sleep(5)
```

## 4. WebSocket Status Update

You'll need to ensure your WebSocket component correctly forwards the camera status and command response messages to the appropriate components. Here's the essential additions needed:

```typescript
// Add to the WebSocket message handler in the `socket.onmessage` callback

socket.onmessage = (message) => {
  // Call the original handler if it exists
  if (originalOnMessage) {
    originalOnMessage.call(socket, message);
  }

  try {
    const data = JSON.parse(message.data);

    // Process message based on type
    if (data.name === "pong") {
      // Handle ping response
      // ... existing code ...
    } else if (data.name === "battery_info") {
      // Handle battery information
      // ... existing code ...
    } else if (data.name === "camera_status") {
      // Forward camera status to CameraFeed component
      window.dispatchEvent(
        new CustomEvent("camera:status-update", {
          detail: data.data,
        })
      );
    } else if (data.name === "command_response") {
      // Forward command responses to DebugState component
      window.dispatchEvent(
        new CustomEvent("command:response", {
          detail: data.data,
        })
      );
    }

    // Log all received messages for debug
    trackWsMessage("received", data);
  } catch (e) {
    console.error("Error parsing WebSocket message:", e);
    logError("WebSocket message parse error", {
      raw:
        typeof message.data === "string"
          ? message.data.substring(0, 100)
          : "Non-string data",
    });
  }
};
```

These enhancements properly handle the camera warnings, improve the UI states for robot commands, and add WiFi network management functionality. The Python monitoring code now also restarts the camera when the network changes, ensuring continuous operation despite network switches.
