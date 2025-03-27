Below is a consolidated proposal reflecting the architectural and code-level improvements you requested. It includes:

- **Async TTS calls** that don’t block other operations.
- **Camera error detection** and automatic restart, with a WebSocket notification to the client.
- **Robot command results** always returned to the WebSocket with success/fail status and relevant progress messages.
- **Update checking** that differentiates “no updates” from “updates available.”
- **Restart service feedback** on the client side.
- **Camera-connection errors** that prompt the user to check connections and possibly restart.
- **Auto-stop the robot** if no incoming control messages for a certain time, plus small **sound effects** for acceleration/deceleration/drifting.
- **French TTS** for all audible messages and an improved startup sequence.
- **WiFi management** (listing, adding, removing networks, switching between AP and WiFi).
- Code adjustments for performance, error handling, and generally more robust architecture.

The following snippet highlights how the final implementation might look. You can adopt it as-is or adapt to your specific environment. Comments throughout indicate design choices and potential optimizations.

---

## **1. `main.py` (Python)**

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

# Import from robot_hat
from robot_hat import Music, TTS, get_battery_voltage

SERVER_HOST = "127.0.0.1:3001"
PROJECT_DIR = Path(__file__).parent.parent  # /home/pi/ByteRacer
PYTHON_DIR = Path(__file__).parent         # /home/pi/ByteRacer/byteracer

px = Picarx()

# -- Global Flags & States --
stop_speaking_ip = False
previous_use_state = False
music_player = None
camera_active = False
previous_speed = 0
previous_turn = 0
last_control_message_time = time.time()
sound_effects_enabled = True

# Keep track of an active websocket to send camera/command updates if needed
websocket_connection = None

def get_ip():
    """Retrieve the Raspberry Pi’s IP address or fallback to 127.0.0.1."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

async def tts_speak(tts, text):
    """
    Non-blocking TTS function.
    Runs `tts.say()` in a thread so other operations (camera check, WS handle) are not blocked.
    """
    if not tts:
        return
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: tts.say(text))

async def speak_ip_periodically(tts):
    """
    Continuously announce the IP address (in French) until a gamepad input arrives.
    """
    global stop_speaking_ip
    while not stop_speaking_ip:
        ip_address = get_ip()
        await tts_speak(tts, f"Mon adresse IP est {ip_address}")
        await asyncio.sleep(5)

def get_battery_level():
    """
    Convert battery voltage to a rough percentage.
    """
    voltage = get_battery_voltage()
    if voltage >= 7.8:
        return 100
    elif voltage >= 6.7:
        return int((voltage - 6.7) / (7.8 - 6.7) * 100)
    else:
        return 0

def restart_camera_feed():
    """Stop and reinitialize the camera feed, returning True on success."""
    global camera_active
    try:
        print("Restarting camera feed...")
        Vilib.camera_close()
        time.sleep(5)  # Wait for closure
        Vilib.camera_start(vflip=False, hflip=False)
        Vilib.display(local=False, web=True)
        camera_active = True
        print("Camera feed restarted successfully")
        return True
    except Exception as e:
        print(f"Error restarting camera feed: {e}")
        return False

def execute_system_command(cmd, success_msg):
    """Runs a shell command, capturing output. Return True if no error."""
    try:
        print(f"Executing: {cmd}")
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        print(success_msg, result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {e}, output: {e.stderr}")
        return False

# -- Camera & Connection Monitoring Tasks --

async def monitor_camera_status(websocket=None):
    """
    Periodically checks if camera is still running; if not, tries restarting.
    Sends WS notifications on error or restart.
    """
    global camera_active
    while True:
        await asyncio.sleep(10)
        try:
            if camera_active and not Vilib.camera_is_running():
                print("Camera error detected, attempting restart...")
                restart_ok = restart_camera_feed()
                if websocket:
                    await websocket.send(json.dumps({
                        "name": "camera_status",
                        "data": {
                            "status": "restarted" if restart_ok else "error",
                            "message": (
                                "Caméra redémarrée avec succès"
                                if restart_ok else
                                "Problème de caméra détecté. Vérifiez la connexion."
                            ),
                            "timestamp": int(time.time() * 1000)
                        },
                        "createdAt": int(time.time() * 1000)
                    }))
        except Exception as e:
            print(f"Error monitoring camera: {e}")

async def monitor_connection_status():
    """
    If no control messages for 3+ seconds and robot is moving, stop it and play a warning sound.
    """
    global last_control_message_time, music_player
    while True:
        await asyncio.sleep(0.5)
        now = time.time()
        if now - last_control_message_time > 3 and (px.speed != 0 or px.dir_servo_angle != 0):
            print("No control messages recently, stopping robot for safety.")
            px.set_motor_speed(1, 0)
            px.set_motor_speed(2, 0)
            px.set_dir_servo_angle(0)
            if music_player:
                music_player.sound_play_threading('assets/connection_lost.mp3')

async def monitor_network_mode(tts):
    """
    Monitor for IP or mode changes.
    If changed, TTS announcement in French and attempt camera restart if network changed.
    """
    global camera_active, websocket_connection
    last_ip = None
    last_mode = None

    while True:
        ip_address = get_ip()
        changed = (ip_address != last_ip)
        if ip_address.startswith("127."):
            current_mode = "Mode point d'accès"
        else:
            current_mode = "Mode WiFi ou Ethernet"

        if current_mode != last_mode or changed:
            print(f"Network changed: {last_ip} -> {ip_address}")
            await tts_speak(tts, f"Mode réseau changé: {current_mode}")
            if current_mode == "Mode point d'accès":
                await tts_speak(tts, "Veuillez vous connecter au point d'accès du robot. Adresse: 192.168.50.5:3000")
            else:
                await tts_speak(tts, f"Veuillez vous connecter au même réseau et aller à l'adresse {ip_address}:3000")

            # If IP changed, try reinitializing camera
            if changed and camera_active:
                print("IP changed, restarting camera feed for reliability...")
                camera_ok = restart_camera_feed()
                if websocket_connection and hasattr(websocket_connection, "send"):
                    try:
                        await websocket_connection.send(json.dumps({
                            "name": "camera_status",
                            "data": {
                                "status": "restarted" if camera_ok else "error",
                                "message": "Caméra redémarrée suite au changement de réseau" if camera_ok else "Problème caméra après basculement réseau",
                                "timestamp": int(time.time() * 1000)
                            },
                            "createdAt": int(time.time() * 1000)
                        }))
                    except Exception as e:
                        print(f"WS send error for camera status: {e}")

            last_ip = ip_address
            last_mode = current_mode

        await asyncio.sleep(5)

# -- Sound Effects --

def play_driving_sounds(current_speed, prev_speed, current_turn, prev_turn):
    """Simple logic to play acceleration/brake/drift sounds."""
    if not (music_player and sound_effects_enabled):
        return
    # Acceleration
    if abs(current_speed) > abs(prev_speed) + 0.15:
        music_player.sound_play_threading('assets/accelerate.mp3')
    # Deceleration / braking
    elif abs(current_speed) < abs(prev_speed) - 0.15 and abs(prev_speed) > 0.2:
        music_player.sound_play_threading('assets/brake.mp3')
    # Drift
    if abs(current_turn) > 0.7 and abs(prev_turn) <= 0.5:
        music_player.sound_play_threading('assets/drift.mp3')

# -- WiFi Management Helpers --

def list_wifi_networks():
    """Scan for available WiFi using `iwlist`. Return list of SSIDs."""
    networks = []
    try:
        result = subprocess.run(['sudo', 'iwlist', 'wlan0', 'scan'],
                                capture_output=True, text=True)
        for line in result.stdout.split('\n'):
            if 'ESSID:' in line:
                ssid = line.split('ESSID:"')[1].split('"')[0]
                if ssid and ssid not in [n['ssid'] for n in networks]:
                    networks.append({'ssid': ssid})
    except Exception as e:
        print(f"Error scanning WiFi networks: {e}")
    return networks

def get_saved_networks():
    """Return list of SSIDs from wpa_supplicant.conf."""
    networks = []
    try:
        with open('/etc/wpa_supplicant/wpa_supplicant.conf', 'r') as f:
            content = f.read()
        for block in content.split('network={'):
            if 'ssid=' in block:
                ssid = block.split('ssid="')[1].split('"')[0]
                networks.append({'ssid': ssid})
    except Exception as e:
        print(f"Error reading wpa_supplicant.conf: {e}")
    return networks

def add_wifi_network(ssid, password):
    """Append new network block to wpa_supplicant and restart service."""
    try:
        netblock = f'\nnetwork={{\n\tssid="{ssid}"\n\tpsk="{password}"\n\tkey_mgmt=WPA-PSK\n}}\n'
        with open('/etc/wpa_supplicant/wpa_supplicant.conf', 'a') as f:
            f.write(netblock)
        subprocess.run(['sudo', 'systemctl', 'restart', 'wpa_supplicant'], check=True)
        return {"success": True, "message": f"Réseau {ssid} ajouté"}
    except Exception as e:
        return {"success": False, "message": f"Échec ajout réseau: {e}"}

def remove_wifi_network(ssid):
    """Remove a network block from wpa_supplicant by SSID."""
    try:
        with open('/etc/wpa_supplicant/wpa_supplicant.conf', 'r') as f:
            lines = f.readlines()
        new_lines = []
        skip = False
        for line in lines:
            if f'ssid="{ssid}"' in line:
                skip = True
            elif skip and '}' in line:
                skip = False
                continue
            if not skip:
                new_lines.append(line)
        with open('/etc/wpa_supplicant/wpa_supplicant.conf', 'w') as f:
            f.writelines(new_lines)
        subprocess.run(['sudo', 'systemctl', 'restart', 'wpa_supplicant'], check=True)
        return {"success": True, "message": f"Réseau {ssid} supprimé"}
    except Exception as e:
        return {"success": False, "message": f"Erreur suppression réseau: {e}"}

def switch_network_mode(mode):
    """Use `accesspopup` script to toggle AP <-> WiFi modes."""
    try:
        if mode == "ap":
            res = subprocess.run(['sudo', 'accesspopup', '-a'], check=True, capture_output=True)
        else:
            res = subprocess.run(['sudo', 'accesspopup'], check=True, capture_output=True)
        return {"success": True, "message": f"Basculé en mode {'AP' if mode=='ap' else 'WiFi'}"}
    except Exception as e:
        return {"success": False, "message": f"Échec changement mode: {e}"}

# -- Command Execution --

async def execute_robot_command(command, websocket=None, data=None):
    """
    Unified entry point for robot commands:
      - Reboot, Shutdown
      - Restart services
      - Check for updates, etc.
      - WiFi management
    Send progress to the client as needed.
    """
    result = {
        "success": False,
        "message": "Commande inconnue",
        "command": command,
        "status": "failed"
    }
    if data is None:
        data = {}

    # 1) System-level commands
    if command == "restart_robot":
        result.update({
            "success": True,
            "message": "Redémarrage du système...",
            "status": "in_progress",
        })
        if websocket:
            await websocket.send(json.dumps({"name": "command_response","data": result,"createdAt": int(time.time()*1000)}))
        threading.Timer(2.0, lambda: execute_system_command("sudo reboot", "System reboot initiated")).start()
        return result

    elif command == "stop_robot":
        result.update({
            "success": True,
            "message": "Arrêt du système...",
            "status": "in_progress",
        })
        if websocket:
            await websocket.send(json.dumps({"name": "command_response","data": result,"createdAt": int(time.time()*1000)}))
        threading.Timer(2.0, lambda: execute_system_command("sudo shutdown -h now", "System shutdown initiated")).start()
        return result

    elif command == "restart_all_services":
        result["status"] = "in_progress"
        result["message"] = "Redémarrage de tous les services..."
        if websocket:
            await websocket.send(json.dumps({"name": "command_response","data": result,"createdAt": int(time.time()*1000)}))
        success = execute_system_command(f"cd {PYTHON_DIR} && sudo bash ./scripts/restart_services.sh","All services restarted")
        result["success"] = success
        result["status"] = "completed" if success else "failed"
        result["message"] = "Services redémarrés" if success else "Échec du redémarrage"

    elif command == "restart_websocket":
        result["status"] = "in_progress"
        result["message"] = "Redémarrage du service WebSocket..."
        if websocket:
            await websocket.send(json.dumps({"name": "command_response","data": result,"createdAt": int(time.time()*1000)}))
        success = execute_system_command(
            "screen -S eaglecontrol -X quit && cd /home/pi/ByteRacer/eaglecontrol && screen -dmS eaglecontrol bash -c 'bun run start; exec bash'",
            "WebSocket service restarted"
        )
        result["success"] = success
        result["status"] = "completed" if success else "failed"
        result["message"] = "Service WebSocket redémarré" if success else "Échec du redémarrage WebSocket"

    elif command == "restart_web_server":
        result["status"] = "in_progress"
        result["message"] = "Redémarrage du serveur web..."
        if websocket:
            await websocket.send(json.dumps({"name": "command_response","data": result,"createdAt": int(time.time()*1000)}))
        success = execute_system_command(
            "screen -S relaytower -X quit && cd /home/pi/ByteRacer/relaytower && screen -dmS relaytower bash -c 'bun run start; exec bash'",
            "Web server restarted"
        )
        result["success"] = success
        result["status"] = "completed" if success else "failed"
        result["message"] = "Serveur web redémarré" if success else "Échec du redémarrage serveur web"

    elif command == "restart_python_service":
        result.update({
            "success": True,
            "status": "in_progress",
            "message": "Service Python en cours de redémarrage"
        })
        if websocket:
            await websocket.send(json.dumps({"name":"command_response","data":result,"createdAt":int(time.time()*1000)}))
        threading.Timer(1.0, lambda: os._exit(0)).start()
        return result

    elif command == "restart_camera_feed":
        result.update({"status":"in_progress","message":"Redémarrage de la caméra..."})
        if websocket:
            await websocket.send(json.dumps({"name":"command_response","data":result,"createdAt":int(time.time()*1000)}))
        ok = restart_camera_feed()
        result["success"] = ok
        result["status"] = "completed" if ok else "failed"
        result["message"] = "Caméra redémarrée" if ok else "Échec du redémarrage caméra"

    elif command == "check_for_updates":
        result.update({"status":"checking","message":"Vérification des mises à jour..."})
        if websocket:
            await websocket.send(json.dumps({"name":"command_response","data":result,"createdAt":int(time.time()*1000)}))
        process = subprocess.Popen(
            f"cd {PROJECT_DIR} && git fetch && git rev-list HEAD...origin/main --count",
            shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, _ = process.communicate()
        update_count = stdout.decode().strip()
        if update_count == "0":
            result["success"] = True
            result["status"] = "up_to_date"
            result["message"] = "Le système est déjà à jour."
        else:
            result["status"] = "updating"
            result["message"] = f"{update_count} mise(s) à jour trouvée(s). Installation..."
            if websocket:
                await websocket.send(json.dumps({"name":"command_response","data":result,"createdAt":int(time.time()*1000)}))
            upd_ok = execute_system_command(
                f"cd {PROJECT_DIR} && git pull && cd {PYTHON_DIR} && sudo bash ./scripts/update.sh",
                "Mises à jour appliquées."
            )
            result["success"] = upd_ok
            result["status"] = "completed" if upd_ok else "failed"
            result["message"] = "Mises à jour installées" if upd_ok else "Echec d'installation"

    # 2) WiFi management commands
    elif command == "wifi_list_available":
        nets = list_wifi_networks()
        result["success"] = True
        result["message"] = f"Trouvé {len(nets)} réseaux"
        result["networks"] = nets
        result["status"] = "completed"

    elif command == "wifi_list_saved":
        nets = get_saved_networks()
        result["success"] = True
        result["message"] = f"Réseaux enregistrés: {len(nets)}"
        result["networks"] = nets
        result["status"] = "completed"

    elif command == "wifi_add_network":
        if "ssid" not in data or "password" not in data:
            result.update({"success":False,"message":"Paramètres SSID/mot de passe manquants"})
        else:
            out = add_wifi_network(data["ssid"], data["password"])
            result["success"] = out["success"]
            result["message"] = out["message"]
            result["status"] = "completed" if out["success"] else "failed"

    elif command == "wifi_remove_network":
        if "ssid" not in data:
            result.update({"success":False,"message":"SSID manquant"})
        else:
            out = remove_wifi_network(data["ssid"])
            result["success"] = out["success"]
            result["message"] = out["message"]
            result["status"] = "completed" if out["success"] else "failed"

    elif command == "wifi_switch_mode":
        if "mode" not in data or data["mode"] not in ["ap","wifi"]:
            result.update({"success":False,"message":"Paramètre mode invalide: ap ou wifi"})
        else:
            sw = switch_network_mode(data["mode"])
            result["success"] = sw["success"]
            result["message"] = sw["message"]
            result["status"] = "completed" if sw["success"] else "failed"

    return result

def on_message(message, websocket=None):
    """
    Main incoming message handler (from WebSocket).
    - Gamepad input: stop TTS, update control time, play sounds, move robot
    - Robot commands: forward to `handle_command`
    - Battery requests
    """
    global stop_speaking_ip, previous_use_state, music_player
    global last_control_message_time, previous_speed, previous_turn

    try:
        data = json.loads(message)
        if data["name"] == "welcome":
            print(f"Welcome from client: {data['data']['clientId']}")
        elif data["name"] == "gamepad_input":
            stop_speaking_ip = True
            last_control_message_time = time.time()

            # Ex: { speed, turn, turnCameraX, turnCameraY, use }
            turn = float(data["data"].get("turn", 0))
            speed = float(data["data"].get("speed", 0))
            pan = float(data["data"].get("turnCameraX", 0))
            tilt = float(data["data"].get("turnCameraY", 0))
            use = data["data"].get("use", False)

            # Drive sounds
            play_driving_sounds(speed, previous_speed, turn, previous_turn)

            if use and not previous_use_state and music_player:
                music_player.sound_play_threading('assets/horn.mp3')

            previous_use_state = use
            previous_speed = speed
            previous_turn = turn

            # Control the motors
            px.set_motor_speed(1, speed * 100)
            px.set_motor_speed(2, speed * -100)
            px.set_dir_servo_angle(turn * 30)
            px.set_cam_pan_angle(pan * 90)
            if tilt >= 0:
                px.set_cam_tilt_angle(tilt * 65)
            else:
                px.set_cam_tilt_angle(tilt * 35)

        elif data["name"] == "robot_command":
            cmd = data["data"].get("command")
            cmd_data = data["data"].get("data", {})
            if cmd:
                asyncio.create_task(handle_command(cmd, websocket, cmd_data))

        elif data["name"] == "battery_request":
            battery = get_battery_level()
            if websocket:
                asyncio.create_task(send_battery_info(battery, websocket))
        else:
            print("Received unknown message:", data["name"])

    except json.JSONDecodeError:
        print(f"Non-JSON message: {message}")
    except Exception as e:
        print(f"Error processing message: {e}")

async def handle_command(command, websocket, data=None):
    """Wrap `execute_robot_command` to handle any final response sending."""
    try:
        result = await execute_robot_command(command, websocket, data)
        # If final status (not 'in_progress'), send final response
        if websocket and result["status"] not in ("in_progress","checking","updating"):
            await websocket.send(json.dumps({
                "name": "command_response",
                "data": result,
                "createdAt": int(time.time()*1000)
            }))
    except Exception as e:
        print(f"Error {command}: {e}")
        if websocket:
            await websocket.send(json.dumps({
                "name":"command_response",
                "data":{
                    "success":False,
                    "message":f"Erreur: {str(e)}",
                    "command":command,
                    "status":"failed"
                },
                "createdAt":int(time.time()*1000)
            }))

async def send_battery_info(level, ws):
    """Send battery info event."""
    try:
        await ws.send(json.dumps({
            "name":"battery_info",
            "data":{"level":level,"timestamp":int(time.time()*1000)},
            "createdAt":int(time.time()*1000)
        }))
        print(f"Battery: {level}%")
    except Exception as e:
        print(f"Error sending battery: {e}")

async def connect_to_websocket(url):
    """Attempt WS connect, on failure wait 5s and retry indefinitely."""
    global websocket_connection
    while True:
        try:
            async with websockets.connect(url) as ws:
                websocket_connection = ws
                print(f"Connected to {url}. Sending registration.")
                reg = {
                  "name":"client_register",
                  "data": {"type":"car","id":"byteracer-1"},
                  "createdAt":int(time.time()*1000)
                }
                await ws.send(json.dumps(reg))
                # Monitor camera in separate async task
                asyncio.create_task(monitor_camera_status(ws))
                # Listen forever
                while True:
                    msg = await ws.recv()
                    on_message(msg, ws)
        except Exception as e:
            print(f"WS connection error: {e}, retrying in 5s")
            await asyncio.sleep(5)

async def main():
    """
    Entry point:
     - TTS in French
     - Start camera
     - Music instance
     - Speak startup
     - Connect WS
     - Start tasks (monitor net, monitor connection)
    """
    global music_player, camera_active

    # TTS in FR
    tts = TTS()
    tts.lang("fr-FR")

    # Startup announcements
    boot_lines = [
        "Bonjour, je suis ByteRacer",
        "Initialisation des systèmes en cours",
        "Démarrage de la caméra",
        "Connexion au serveur",
        "ByteRacer est prêt!"
    ]

    try:
        Vilib.camera_start(vflip=False, hflip=False)
        Vilib.display(local=False, web=True)
        camera_active = True
    except Exception as e:
        print("Camera error on startup:", e)

    music_player = Music()

    for line in boot_lines:
        await tts_speak(tts, line)
        await asyncio.sleep(0.5)

    # Build ws url
    url = f"ws://{SERVER_HOST}/ws"
    print(f"Connecting to {url}...")

    await asyncio.gather(
        connect_to_websocket(url),
        speak_ip_periodically(tts),
        monitor_network_mode(tts),
        monitor_connection_status(),
    )

if __name__=="__main__":
    try:
        print("ByteRacer starting...")
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down gracefully...")
    finally:
        if camera_active:
            Vilib.camera_close()
        px.forward(0)
        px.set_dir_servo_angle(0)
        px.set_cam_pan_angle(0)
        px.set_cam_tilt_angle(0)
        print("ByteRacer offline.")
```

### Notable Points & Potential Enhancements

1. **Async TTS**: The TTS calls are scheduled via `run_in_executor` so the main event loop remains responsive.
2. **Camera Monitoring**: If the camera feed is closed or an error occurs, we attempt a restart and notify the client via WebSocket.
3. **Robot Commands**: Any external actions (reboot, updates, WiFi changes) are run with logging and returned to the client with status flags (`in_progress`, `completed`, or `failed`).
4. **Connection Safety**: If the robot doesn’t receive input for 3 seconds while in motion, we stop motors and play a “connection lost” sound.
5. **Sound Effects**: A minimal “FSM approach” checking changes in speed and turn for simple accelerate/brake/drift triggers.
6. **WiFi Management**: Basic scanning, saving, and removing networks, plus toggling AP mode; all run via system commands that you can adapt.
7. **French TTS**: All strings adjusted to French. Adjust them further to refine messages as needed.

---

## **2. Client-Side: Key Changes**

Below is an example of how you might **handle UI states** for commands, camera warnings, and WiFi interactions in your React/Next.js code. These changes ensure:

- **“command_response”** events from Python are displayed with progress/spinner, success, or error states.
- **Camera errors** produce a warning overlay.
- **WiFi management** is a new tab, scanning networks, adding saved networks, etc.

**WebSocketStatus.tsx**  
(Where we handle the `camera_status` or `command_response` events)

```tsx
// Highlights from an updated WebSocketStatus that listens for camera+command updates

useEffect(() => {
  socket.onmessage = (msg) => {
    try {
      const event = JSON.parse(msg.data);
      trackWsMessage("received", event);

      switch (event.name) {
        case "pong":
          // measure ping
          break;
        case "battery_info":
          setBatteryLevel(event.data.level);
          window.dispatchEvent(
            new CustomEvent("debug:battery-update", {
              detail: { level: event.data.level },
            })
          );
          break;
        case "camera_status":
          // Notify camera feed
          window.dispatchEvent(
            new CustomEvent("camera:status-update", { detail: event.data })
          );
          break;
        case "command_response":
          // Let debug panel or others track states
          window.dispatchEvent(
            new CustomEvent("command:response", { detail: event.data })
          );
          break;
        default:
          break;
      }
    } catch (e) {
      logError("Error parsing WebSocket message", { messageData: msg.data });
    }
  };
}, [socket]);
```

**DebugState.tsx**  
(Large “debug console” that includes WiFi scanning, command states, etc.)

```tsx
// ...
const [commandStates, setCommandStates] = useState<
  Record<string, { status: string; message: string }>
>({});
// ...
useEffect(() => {
  const handleCommandResponse = (e: CustomEvent) => {
    const { command, status, message, success } = e.detail;
    setCommandStates((prev) => ({
      ...prev,
      [command]: {
        status: status ?? (success ? "success" : "error"),
        message: message ?? (success ? "Ok" : "Erreur"),
      },
    }));
  };
  window.addEventListener(
    "command:response",
    handleCommandResponse as EventListener
  );
  return () =>
    window.removeEventListener(
      "command:response",
      handleCommandResponse as EventListener
    );
}, []);
// ...
```

You would then pass these states into your UI components (buttons, etc.) so the user sees real-time success/failure messages for reboots, updates, or WiFi changes.

---

## **3. `restart_services.sh` & `update.sh`**

Make sure your scripts are placed in `byteracer/scripts/` (or wherever you prefer), and they handle the _restart all services_ and _update_ logic. For example:

```bash
#!/bin/bash
# restart_services.sh
echo "Restarting ByteRacer services..."

screen -S eaglecontrol -X quit || true
screen -S relaytower -X quit || true
screen -S byteracer -X quit || true

sleep 2

cd /home/pi/ByteRacer/eaglecontrol
screen -dmS eaglecontrol bun run start

cd /home/pi/ByteRacer/relaytower
screen -dmS relaytower bun run start

cd /home/pi/ByteRacer/byteracer
screen -dmS byteracer sudo python3 main.py

echo "All services restarted."
```

```bash
#!/bin/bash
# update.sh
echo "Updating ByteRacer..."

cd /home/pi/ByteRacer

# Update Relaytower
if [ -d "relaytower" ]; then
  cd relaytower
  bun install
  bun run build
  cd ..
fi

# Eaglecontrol
if [ -d "eaglecontrol" ]; then
  cd eaglecontrol
  bun install
  cd ..
fi

# Byteracer
if [ -d "byteracer" ]; then
  cd byteracer
  if [ -f requirements.txt ]; then
    while read line; do
      # skip comments
      # ...
    done < requirements.txt
  fi
  if [ -f install.sh ]; then
    sudo bash install.sh
  fi
  cd ..
fi

echo "Update completed. Restarting services..."
sudo bash ./scripts/restart_services.sh
```

---

## **4. Additional Architecture / Deployment Tips**

- **Systemd** vs `screen`: You might prefer `systemd` service definitions for each part instead of `screen`. This ensures automatic restarts, logs in `journalctl`, etc.
- **Asset Files**: `accelerate.mp3`, `brake.mp3`, `drift.mp3`, `connection_lost.mp3`, `horn.mp3` should exist in `byteracer/assets/`.
- **Access Point**: If `accesspopup` is your script, ensure it’s placed in `/usr/local/bin` or equivalent and is fully tested.
- **Security**: WiFi credentials pass in JSON to Python. That’s typically local/behind your AP or LAN, so it might be acceptable. Otherwise, consider encryption or restricting access.

---

## **5. High-Level Summary of Advice**

1. **Async I/O**: The largest potential bottleneck was TTS blocking. Now it’s asynchronous.
2. **Camera Reliability**: Checks every 10 seconds if `Vilib.camera_is_running()`. If not, tries to restore and notifies the client.
3. **Network Switching**: On IP changes (like from AP to WiFi or vice versa), the camera is also restarted to mitigate typical CSI or PiCamera reinit issues.
4. **User Feedback**: We track command states (in_progress → completed, or up_to_date, etc.) and show them in the client’s UI (buttons become spinners or success/fail icons).
5. **Enhancements**: Optional expansions include store logs, scheduling tasks, a more robust approach to concurrency (like if two commands are triggered at once), better WiFi error messages, etc.

With this final structure, you have:

- **Non-blocking TTS**
- **Automatic Camera Recovery**
- **Detailed Command/Update statuses**
- **French voice prompts**
- **WiFi scans and AP toggles**
- **Automatic robot safety stop**

All combined, it should give ByteRacer a more polished user experience and robust operational handling. Feel free to refine any messages, especially the French TTS lines, to better suit your style or add further safety checks for edge cases.

_Bonne chance et bonne continuation !_
