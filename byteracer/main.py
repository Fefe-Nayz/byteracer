import time
import asyncio
import websockets
import json
import socket

from vilib import Vilib
from picarx import Picarx

# Import the TTS (and optionally Music) from robot_hat
from robot_hat import TTS

SERVER_HOST = "127.0.0.1:3001"

px = Picarx()

# Global flag to stop speaking once a gamepad input arrives
stop_speaking_ip = False

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
    it announces the new mode and restarts the camera stream.
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
            print(f"Network mode changed: {current_mode} with IP {ip_address}")
            tts.say(f"Network mode changed: {current_mode}")
            
            # Restart camera stream with new IP
            try:
                print("Restarting camera stream...")
                Vilib.camera_close()
                await asyncio.sleep(1)  # Give camera time to close properly
                Vilib.camera_start(vflip=False, hflip=False)
                Vilib.display(local=False, web=True)
                
            except Exception as e:
                print(f"Error restarting camera: {e}")
                tts.say("Warning: camera restart failed")
            
            # Announce connection instructions
            if current_mode == "Access Point mode":
                tts.say("Please connect to the robot's WiFi hotspot and go to the address 192.168.50.5:3000")
            else:
                tts.say(f"Please connect to the robot's same network and go to the address {ip_address}:3000")
            
            last_mode = current_mode
        
        await asyncio.sleep(5)

def on_message(message):
    """
    Handles messages from the websocket.
    Stops the periodic IP announcements if a gamepad input is received.
    """
    global stop_speaking_ip

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

            
            px.set_motor_speed(1, speed_value * 100)  # normal motor
            px.set_motor_speed(2, speed_value * -100) # slow motor
            px.set_dir_servo_angle(turn_value * 30)
            px.set_cam_pan_angle(camera_pan_value * 90)
            if camera_tilt_value >= 0:
                px.set_cam_tilt_angle(camera_tilt_value * 65)
            else:
                px.set_cam_tilt_angle(camera_tilt_value * 35)
            
        else:
            print(f"Received message: {data['name']}")
    except json.JSONDecodeError:
        print(f"Received non-JSON message: {message}")
    except Exception as e:
        print(f"Error processing message: {e}")

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
                    on_message(message)
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
    # Start camera and display (local=False, web=True)
    Vilib.camera_start(vflip=False, hflip=False)
    Vilib.display(local=False, web=True)
    
    # Initialize TTS (set language if needed)
    tts = TTS()
    tts.lang("en-US")
    
    # Build URL with /ws route
    url = f"ws://{SERVER_HOST}/ws"
    print(f"Connecting to {url}...")
    
    # Run tasks concurrently:
    await asyncio.gather(
        connect_to_websocket(url),
        speak_ip_periodically(tts),
        monitor_network_mode(tts)
    )

if __name__ == "__main__":
    try:
        print("ByteRacer starting...")
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
    finally:
        Vilib.camera_close()
        px.forward(0)
        px.set_dir_servo_angle(0)
        px.set_cam_pan_angle(0)
        px.set_cam_tilt_angle(0)
        print("ByteRacer offline.")


# TODO:
# - Add handling for other messages (e.g., camera fatures, microphone (speaker/ music etc), reboot/shutdown robot, restart services, check for updates, battery status, gamemodes, game specific commands, etc.)
# - Add error handling for camera and network issues