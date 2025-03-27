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

# Global flags / states
stop_speaking_ip = False    # We'll stop IP announcements when a non-car client connects
previous_use_state = False
music_player = None
camera_active = False

# For auto-stop if no control messages
last_control_message_time = time.time()

# For minimal sensor-based speed estimate
estimated_speed = 0.0
last_accel_time = time.time()

# For camera monitoring
websocket_connection = None

# If user stops controlling (or any WS message stops), we do an emergency stop if the robot is moving
sound_effects_enabled = True

# Helper: get the Pi’s IP address
def get_ip():
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

# Non-blocking TTS
async def tts_speak(tts, text):
    """Run TTS in a separate thread so it won't block other tasks."""
    if not tts:
        return
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: tts.say(text))

async def speak_ip_periodically(tts):
    """
    Keep announcing the IP address every 5 seconds until a non-car client connects,
    meaning `stop_speaking_ip` is set to True.
    """
    global stop_speaking_ip
    while not stop_speaking_ip:
        ip_address = get_ip()
        await tts_speak(tts, f"Mon adresse IP est {ip_address}")
        await asyncio.sleep(5)

def get_battery_level():
    """
    Approximate battery percentage from voltage:
      - 7.8V+ => 100%
      - ~6.7-7.8 => linear from 0% to 100%
      - <6.7 => 0%
    """
    v = get_battery_voltage()
    if v >= 7.8:
        return 100
    elif v >= 6.7:
        return int((v - 6.7) / (7.8 - 6.7) * 100)
    else:
        return 0

def restart_camera_feed():
    """Stop & restart the camera feed in-process."""
    global camera_active
    try:
        print("Restarting camera feed...")
        Vilib.camera_close()
        time.sleep(3)
        Vilib.camera_start(vflip=False, hflip=False)
        Vilib.display(local=False, web=True)
        camera_active = True
        print("Camera feed restarted successfully")
        return True
    except Exception as e:
        print(f"Error restarting camera feed: {e}")
        return False

def execute_system_command(cmd, success_msg):
    """Helper: run a shell command, returning True if no error thrown."""
    try:
        print(f"Executing: {cmd}")
        res = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        print(success_msg)
        print("Output:", res.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {e}, Error: {e.stderr}")
        return False

# Sensor reading stubs; adjust to your PiCar library calls
def read_ultrasonic_distance():
    """
    Return ultrasonic sensor distance in cm.
    Adjust or wrap as needed: px.get_distance(), px.ultrasonic.read(), etc.
    """
    try:
        return px.ultrasonic.read()
    except:
        return 9999  # If there's an error, treat as no obstacle

def read_line_detection():
    """
    Return line-sensor data array (3 grayscale or binary channels).
    """
    try:
        return px.grayscale_module.get_grayscale_data()
    except:
        return [0, 0, 0]

def read_accelerometer():
    """
    Return (ax, ay, az). If no IMU is present, consider returning (0,0,0).
    """
    try:
        return (0.0, 0.0, 0.0)  # Stub
    except:
        return (0.0, 0.0, 0.0)

async def monitor_camera_status(ws=None):
    """
    Periodically check if camera feed is running; if not, try to restart & inform client.
    """
    global camera_active
    while True:
        await asyncio.sleep(10)
        try:
            if camera_active and not Vilib.camera_is_running():
                print("Camera feed not running, attempting restart.")
                restarted = restart_camera_feed()
                if ws:
                    await ws.send(json.dumps({
                        "name": "camera_status",
                        "data": {
                            "status": "restarted" if restarted else "error",
                            "message": (
                                "Caméra redémarrée avec succès"
                                if restarted
                                else "Problème caméra, vérifiez la connexion."
                            ),
                            "timestamp": int(time.time()*1000),
                        },
                        "createdAt": int(time.time()*1000),
                    }))
        except Exception as e:
            print("Camera monitor error:", e)

async def monitor_connection_status():
    """
    If no gamepad_input for >3s, but robot is moving, we do an emergency stop + sound effect.
    """
    global last_control_message_time, music_player
    while True:
        await asyncio.sleep(0.5)
        now = time.time()
        if (now - last_control_message_time > 3) and (px.speed != 0 or px.dir_servo_angle != 0):
            print("No control input for 3s, stopping for safety.")
            px.set_motor_speed(1, 0)
            px.set_motor_speed(2, 0)
            px.set_dir_servo_angle(0)
            if music_player:
                music_player.sound_play_threading('assets/connection_lost.mp3')

async def monitor_network_mode(tts):
    """
    On IP changes (like AP <-> WiFi transitions), do TTS announcements and optionally camera restarts.
    """
    global camera_active, websocket_connection
    last_ip = None
    last_mode = None
    while True:
        ip = get_ip()
        changed = (ip != last_ip)
        if ip.startswith("127."):
            mode = "Mode point d'accès"
        else:
            mode = "Mode WiFi ou Ethernet"
        if mode != last_mode or changed:
            print(f"Network changed: {last_ip} -> {ip}")
            await tts_speak(tts, f"Mode réseau changé: {mode}")
            if mode == "Mode point d'accès":
                await tts_speak(tts, "Veuillez vous connecter au point d'accès du robot et aller à l'adresse 192.168.50.5:3000")
            else:
                await tts_speak(tts, f"Veuillez vous connecter au même réseau et aller à l'adresse {ip}:3000")
            if changed and camera_active:
                reok = restart_camera_feed()
                if websocket_connection and hasattr(websocket_connection, "send"):
                    msg = {
                        "name": "camera_status",
                        "data": {
                            "status": "restarted" if reok else "error",
                            "message": "Caméra redémarrée après changement de réseau"
                                       if reok else "Problème caméra après changement de réseau",
                            "timestamp": int(time.time()*1000)
                        },
                        "createdAt": int(time.time()*1000)
                    }
                    try:
                        await websocket_connection.send(json.dumps(msg))
                    except:
                        pass
            last_ip = ip
            last_mode = mode
        await asyncio.sleep(5)

def play_driving_sounds(curr_speed, prev_speed, curr_turn, prev_turn):
    global sound_effects_enabled, music_player
    if not (sound_effects_enabled and music_player):
        return
    # Simple logic for acceleration, braking, drifting
    if abs(curr_speed) > abs(prev_speed) + 0.15:
        music_player.sound_play_threading('assets/accelerate.mp3')
    elif abs(curr_speed) < abs(prev_speed) - 0.15 and abs(prev_speed) > 0.2:
        music_player.sound_play_threading('assets/brake.mp3')
    if abs(curr_turn) > 0.7 and abs(prev_turn) <= 0.5:
        music_player.sound_play_threading('assets/drift.mp3')

# sensor_loop => read sensors, do emergency stops if needed, send data over WS
async def sensor_loop():
    global estimated_speed, last_accel_time
    global websocket_connection

    emergency_stop = False

    while True:
        await asyncio.sleep(0.2)  # ~5Hz

        # 1) Ultrasonic distance
        dist = read_ultrasonic_distance()
        if dist < 15.0:
            print("Obstacle near - stopping.")
            px.set_motor_speed(1, 0)
            px.set_motor_speed(2, 0)
            px.set_dir_servo_angle(0)
            emergency_stop = True
            if music_player:
                music_player.sound_play_threading('assets/warning.mp3')
        else:
            if emergency_stop and dist > 20.0:
                print("Clearing emergency stop.")
                emergency_stop = False

        # 2) Line detection => treat as cliff detection if sum too low
        line_data = read_line_detection()
        if sum(line_data) < 30:  # example threshold
            print("Cliff or line-edge detected, stopping!")
            px.set_motor_speed(1, 0)
            px.set_motor_speed(2, 0)
            emergency_stop = True
            if music_player:
                music_player.sound_play_threading('assets/warning.mp3')

        # 3) Accelerometer => naive integration for speed
        accel = read_accelerometer()
        now = time.time()
        dt = now - last_accel_time
        last_accel_time = now

        ax = accel[0]
        estimated_speed += ax * dt

        if abs(estimated_speed) < 0.01:
            estimated_speed = 0.0
        if estimated_speed > 1.0:
            estimated_speed = 1.0
        if estimated_speed < -1.0:
            estimated_speed = -1.0

        # 4) Send sensor data if WS connected
        if websocket_connection:
            data_msg = {
                "name": "sensor_update",
                "data": {
                    "distance": dist,
                    "line_data": line_data,
                    "imu_speed_est": round(estimated_speed, 2)
                },
                "createdAt": int(time.time()*1000)
            }
            try:
                await websocket_connection.send(json.dumps(data_msg))
            except:
                pass

# WiFi management functions
def list_wifi_networks():
    """Scan for available WiFi using e.g. `iwlist wlan0 scan`."""
    networks = []
    try:
        result = subprocess.run(['sudo','iwlist','wlan0','scan'], capture_output=True, text=True)
        for line in result.stdout.split('\n'):
            if 'ESSID:' in line:
                ssid = line.split('ESSID:"')[1].split('"')[0]
                if ssid and ssid not in [n['ssid'] for n in networks]:
                    networks.append({'ssid': ssid})
    except Exception as e:
        print("WiFi scan error:", e)
    return networks

def get_saved_networks():
    """Return list of SSIDs from /etc/wpa_supplicant/wpa_supplicant.conf."""
    networks = []
    try:
        with open('/etc/wpa_supplicant/wpa_supplicant.conf', 'r') as f:
            content = f.read()
        for block in content.split('network={'):
            if 'ssid=' in block:
                ssid = block.split('ssid="')[1].split('"')[0]
                networks.append({'ssid': ssid})
    except Exception as e:
        print("wpa_supplicant read error:", e)
    return networks

def add_wifi_network(ssid, password):
    """Append new network block and restart wpa_supplicant."""
    try:
        netblock = f'\nnetwork={{\n\tssid="{ssid}"\n\tpsk="{password}"\n\tkey_mgmt=WPA-PSK\n}}\n'
        with open('/etc/wpa_supplicant/wpa_supplicant.conf','a') as f:
            f.write(netblock)
        subprocess.run(['sudo','systemctl','restart','wpa_supplicant'], check=True)
        return {"success":True, "message":f"Réseau {ssid} ajouté"}
    except Exception as e:
        return {"success":False, "message":f"Échec ajout réseau: {e}"}

def remove_wifi_network(ssid):
    """Remove a block from wpa_supplicant.conf by matching ssid."""
    try:
        with open('/etc/wpa_supplicant/wpa_supplicant.conf','r') as f:
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
        with open('/etc/wpa_supplicant/wpa_supplicant.conf','w') as f:
            f.writelines(new_lines)
        subprocess.run(['sudo','systemctl','restart','wpa_supplicant'], check=True)
        return {"success":True, "message":f"Réseau {ssid} supprimé"}
    except Exception as e:
        return {"success":False, "message":f"Erreur suppression réseau: {e}"}

def switch_network_mode(mode):
    """Toggle AP <-> WiFi client mode using your `accesspopup` script."""
    try:
        if mode == "ap":
            # Switch to AP
            res = subprocess.run(['sudo','accesspopup','-a'], check=True, capture_output=True)
        else:
            # Switch to WiFi
            res = subprocess.run(['sudo','accesspopup'], check=True, capture_output=True)
        return {
            "success":True,
            "message":f"Basculé en mode {'point d accès' if mode=='ap' else 'WiFi'}",
            "output": res.stdout.decode()
        }
    except Exception as e:
        return {"success":False, "message":f"Échec changement mode: {e}"}

async def execute_robot_command(command, ws=None, data=None):
    """
    Central place to handle robot commands:
      - Reboot, shutdown
      - Restart services
      - Check updates
      - WiFi mgmt
      - TTS text
    """
    if data is None:
        data = {}

    result = {
        "success":False,
        "message":"Commande inconnue",
        "command":command,
        "status":"failed"
    }
    if command == "restart_robot":
        result.update({
            "success":True,
            "message":"Redémarrage du système...",
            "status":"in_progress"
        })
        if ws:
            await ws.send(json.dumps({
                "name": "command_response",
                "data": result,
                "createdAt": int(time.time()*1000)
            }))
        # Actually reboot
        threading.Timer(2.0, lambda: execute_system_command("sudo reboot","System reboot initiated")).start()
        return result

    elif command == "stop_robot":
        result.update({
            "success":True,
            "message":"Arrêt du système...",
            "status":"in_progress"
        })
        if ws:
            await ws.send(json.dumps({
                "name":"command_response",
                "data":result,
                "createdAt":int(time.time()*1000)
            }))
        threading.Timer(2.0, lambda: execute_system_command("sudo shutdown -h now","System shutdown initiated")).start()
        return result

    elif command == "restart_all_services":
        result["status"] = "in_progress"
        result["message"] = "Redémarrage de tous les services..."
        if ws:
            await ws.send(json.dumps({
                "name":"command_response",
                "data":result,
                "createdAt":int(time.time()*1000)
            }))
        success = execute_system_command(f"cd {PYTHON_DIR} && sudo bash ./scripts/restart_services.sh","All services restarted")
        result["success"] = success
        result["status"] = "completed" if success else "failed"
        result["message"] = "Services redémarrés" if success else "Échec du redémarrage"

    elif command == "restart_websocket":
        result["status"] = "in_progress"
        result["message"] = "Redémarrage du service WebSocket..."
        if ws:
            await ws.send(json.dumps({
                "name":"command_response",
                "data":result,
                "createdAt":int(time.time()*1000)
            }))
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
        if ws:
            await ws.send(json.dumps({
                "name":"command_response",
                "data":result,
                "createdAt":int(time.time()*1000)
            }))
        success = execute_system_command(
            "screen -S relaytower -X quit && cd /home/pi/ByteRacer/relaytower && screen -dmS relaytower bash -c 'bun run build && bun run start; exec bash'",
            "Web server restarted"
        )
        result["success"] = success
        result["status"] = "completed" if success else "failed"
        result["message"] = "Serveur web redémarré" if success else "Échec du redémarrage du serveur web"

    elif command == "restart_python_service":
        result.update({
            "success":True,
            "status":"in_progress",
            "message":"Service Python en cours de redémarrage"
        })
        if ws:
            await ws.send(json.dumps({
                "name":"command_response",
                "data":result,
                "createdAt":int(time.time()*1000)
            }))
        # forcibly exit => systemd or screen restarts it
        threading.Timer(1.0, lambda: os._exit(0)).start()
        return result

    elif command == "restart_camera_feed":
        result.update({"status":"in_progress","message":"Redémarrage de la caméra..."})
        if ws:
            await ws.send(json.dumps({
                "name":"command_response",
                "data":result,
                "createdAt":int(time.time()*1000)
            }))
        ok = restart_camera_feed()
        result["success"] = ok
        result["status"] = "completed" if ok else "failed"
        result["message"] = "Caméra redémarrée" if ok else "Échec du redémarrage caméra"

    elif command == "check_for_updates":
        # Detailed check (fetch, compare HEAD)
        result["status"] = "checking"
        result["message"] = "Vérification des mises à jour..."
        if ws:
            await ws.send(json.dumps({
                "name":"command_response",
                "data":result,
                "createdAt":int(time.time()*1000)
            }))
        # Check if updates available
        process = subprocess.Popen(
            f"cd {PROJECT_DIR} && git fetch && git rev-list HEAD...origin/main --count",
            shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, stderr = process.communicate()
        update_count = stdout.decode().strip()
        if update_count == "0":
            result.update({
                "success":True,
                "status":"up_to_date",
                "message":"Le système est déjà à jour"
            })
        else:
            result["status"] = "updating"
            result["message"] = f"{update_count} mise(s) à jour trouvée(s). Installation..."
            if ws:
                await ws.send(json.dumps({
                    "name":"command_response",
                    "data":result,
                    "createdAt":int(time.time()*1000)
                }))
            # pull + update.sh
            update_ok = execute_system_command(
                f"cd {PROJECT_DIR} && git pull && cd {PYTHON_DIR} && sudo bash ./scripts/update.sh",
                "Mises à jour appliquées"
            )
            result["success"] = update_ok
            result["status"] = "completed" if update_ok else "failed"
            result["message"] = "Mises à jour installées" if update_ok else "Échec de l'installation des mises à jour"

    elif command == "wifi_list_available":
        nets = list_wifi_networks()
        result.update({
            "success":True,
            "message": f"Trouvé {len(nets)} réseaux",
            "networks": nets,
            "status":"completed"
        })

    elif command == "wifi_list_saved":
        nets = get_saved_networks()
        result.update({
            "success":True,
            "message": f"Réseaux enregistrés: {len(nets)}",
            "networks": nets,
            "status":"completed"
        })

    elif command == "wifi_add_network":
        if "ssid" not in data or "password" not in data:
            result.update({
                "success":False,
                "message":"Paramètres SSID/mot de passe manquants",
                "status":"failed"
            })
        else:
            out = add_wifi_network(data["ssid"], data["password"])
            result.update({
                "success": out["success"],
                "message": out["message"],
                "status":"completed" if out["success"] else "failed"
            })

    elif command == "wifi_remove_network":
        if "ssid" not in data:
            result.update({"success":False,"message":"SSID manquant","status":"failed"})
        else:
            out = remove_wifi_network(data["ssid"])
            result.update({
                "success": out["success"],
                "message": out["message"],
                "status":"completed" if out["success"] else "failed"
            })

    elif command == "wifi_switch_mode":
        if "mode" not in data or data["mode"] not in ["ap","wifi"]:
            result.update({"success":False,"message":"Mode invalide. Use 'ap' or 'wifi'","status":"failed"})
        else:
            sw = switch_network_mode(data["mode"])
            result.update({
                "success":sw["success"],
                "message":sw["message"],
                "status":"completed" if sw["success"] else "failed"
            })

    elif command == "tts_text":
        # Let the robot speak text from the user
        text_to_speak = data.get("text","").strip()
        if text_to_speak:
            # Non-blocking TTS
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, lambda: px.tts.say(text_to_speak))
            result.update({"success":True,"message":"Message en cours de lecture","status":"completed"})
        else:
            result["message"] = "Aucun texte fourni."

    return result

def on_message(message, ws=None):
    """
    Main incoming message handler from the WebSocket side:
      - gamepad_input
      - robot_command
      - battery_request
      - etc.

    We ONLY stop the repeated IP announcements if a new client registers as non-car (or "controller"/"viewer").
    """
    global stop_speaking_ip, previous_use_state, music_player
    global last_control_message_time

    try:
        data = json.loads(message)
        if data["name"] == "client_register":
            # If type != "car", we set stop_speaking_ip = True
            ctype = data["data"].get("type","viewer")
            if ctype != "car":
                stop_speaking_ip = True

        elif data["name"] == "gamepad_input":
            last_control_message_time = time.time()
            turn = float(data["data"].get("turn",0))
            speed = float(data["data"].get("speed",0))
            pan = float(data["data"].get("turnCameraX",0))
            tilt = float(data["data"].get("turnCameraY",0))
            use = bool(data["data"].get("use",False))

            # Sound effect logic
            # We could keep track of previous speed/turn in global variables if needed
            # For simpler approach, we re-check
            # but let's store them in function-level static or global
            # We'll keep them as global
            on_message.previous_speed = getattr(on_message,"previous_speed",0)
            on_message.previous_turn = getattr(on_message,"previous_turn",0)

            play_driving_sounds(speed, on_message.previous_speed, turn, on_message.previous_turn)

            if use and not previous_use_state and music_player:
                music_player.sound_play_threading('assets/horn.mp3')

            previous_use_state = use
            on_message.previous_speed = speed
            on_message.previous_turn = turn

            # Move robot
            px.set_motor_speed(1, speed*100)
            px.set_motor_speed(2, speed*-100)
            px.set_dir_servo_angle(turn*30)
            px.set_cam_pan_angle(pan*90)
            if tilt>=0:
                px.set_cam_tilt_angle(tilt*65)
            else:
                px.set_cam_tilt_angle(tilt*35)

        elif data["name"] == "robot_command":
            cmd = data["data"].get("command")
            cmd_data = data["data"].get("data",{})
            if cmd:
                asyncio.create_task(handle_command(cmd, ws, cmd_data))

        elif data["name"] == "battery_request":
            lvl = get_battery_level()
            if ws:
                asyncio.create_task(send_battery_info(lvl, ws))

    except Exception as e:
        print("on_message error:", e)

async def handle_command(cmd, ws, data=None):
    try:
        result = await execute_robot_command(cmd, ws, data)
        # If final status => send final message
        if ws and result["status"] not in ["in_progress","checking","updating"]:
            await ws.send(json.dumps({
                "name":"command_response",
                "data":result,
                "createdAt":int(time.time()*1000)
            }))
    except Exception as e:
        print(f"handle_command error: {e}")
        if ws:
            await ws.send(json.dumps({
                "name":"command_response",
                "data":{
                    "success":False,
                    "message":f"Erreur: {str(e)}",
                    "command":cmd,
                    "status":"failed"
                },
                "createdAt":int(time.time()*1000)
            }))

async def send_battery_info(level, ws):
    try:
        await ws.send(json.dumps({
            "name":"battery_info",
            "data":{
                "level":level,
                "timestamp":int(time.time()*1000)
            },
            "createdAt":int(time.time()*1000)
        }))
    except Exception as e:
        print("Battery info send error:", e)

async def connect_to_websocket(url):
    global websocket_connection
    while True:
        try:
            async with websockets.connect(url) as wsc:
                websocket_connection = wsc
                print(f"Connected to {url}")
                # register as car
                reg = {
                    "name":"client_register",
                    "data":{"type":"car","id":"byteracer-1"},
                    "createdAt":int(time.time()*1000)
                }
                await wsc.send(json.dumps(reg))
                # Start camera monitor
                asyncio.create_task(monitor_camera_status(wsc))
                # Listen for incoming
                while True:
                    msg = await wsc.recv()
                    on_message(msg, wsc)
        except Exception as e:
            print("WS error:", e)
            await asyncio.sleep(5)

async def main():
    global music_player, camera_active
    # TTS in French
    tts = TTS()
    tts.lang("fr-FR")

    boot_lines = [
        "Bonjour, je suis ByteRacer",
        "Démarrage de la caméra",
        "Connexion au serveur WebSocket",
        "Robot prêt!"
    ]

    # Start camera
    try:
        Vilib.camera_start(vflip=False, hflip=False)
        Vilib.display(local=False, web=True)
        camera_active = True
    except Exception as e:
        print("Camera start error:", e)

    music_player = Music()

    # Speak boot lines
    for line in boot_lines:
        await tts_speak(tts, line)
        await asyncio.sleep(0.5)

    url = f"ws://{SERVER_HOST}/ws"
    print("Connecting to", url)

    # Start sensor loop
    asyncio.create_task(sensor_loop())

    await asyncio.gather(
        connect_to_websocket(url),
        speak_ip_periodically(tts),
        monitor_network_mode(tts),
        monitor_connection_status()
    )

if __name__=="__main__":
    try:
        print("ByteRacer starting up...")
        asyncio.run(main())
    except KeyboardInterrupt:
        print("KeyboardInterrupt => shutting down.")
    finally:
        if camera_active:
            Vilib.camera_close()
        px.forward(0)
        px.set_dir_servo_angle(0)
        px.set_cam_pan_angle(0)
        px.set_cam_tilt_angle(0)
        print("ByteRacer offline.")