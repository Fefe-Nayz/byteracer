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
    A helper function to retrieve the robot's IP address.
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
    Asynchronous loop to speak the robot's IP address every 5 seconds,
    until a gamepad input is received (stop_speaking_ip = True).
    """
    global stop_speaking_ip
    
    while not stop_speaking_ip:
        ip_address = get_ip()
        # Speak the IP address
        tts.say(f"My IP address is {ip_address}")
        # Wait 5 seconds before speaking again
        await asyncio.sleep(5)

def on_message(message):
    """
    Handle messages coming from the websocket.
    If 'gamepad_input' is detected, stop the IP announcement.
    """
    global stop_speaking_ip
    
    try:
        data = json.loads(message)
        if data["name"] == "welcome":
            print(f"Received welcome message, client ID: {data['data']['clientId']}")
        elif data["name"] == "gamepad_input":
            print(f"Received gamepad input: {data['data']}")
            
            # ** Once we receive any gamepad input, stop speaking the IP. **
            stop_speaking_ip = True

            turn_value = data["data"].get("turn", 0)
            speed_value = data["data"].get("speed", 0)
            camera_pan_value = data["data"].get("turnCameraX", 0)
            camera_tilt_value = data["data"].get("turnCameraY", 0)
            
            px.forward(speed_value * 100)
            px.set_dir_servo_angle(turn_value * 30)
            px.set_cam_pan_angle(camera_pan_value * 30)
            px.set_cam_tilt_angle(camera_tilt_value * 30)
            
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
    - Starts camera
    - Displays locally and via web
    - Creates two tasks:
        1) Connect to the websocket server
        2) Periodically speak the IP address
    """
    # Initialize camera
    Vilib.camera_start(vflip=False, hflip=False)
    Vilib.display(local=False, web=True)
    
    # Initialize TTS (set language if needed)
    tts = TTS()
    tts.lang("en-US")
    
    # Build URL with /ws route
    url = f"ws://{SERVER_HOST}/ws"
    print(f"Connecting to {url}...")

    # Run both tasks concurrently
    # Task A: Websocket connection
    # Task B: Speak IP every 5 seconds until gamepad input
    await asyncio.gather(
        connect_to_websocket(url),
        speak_ip_periodically(tts)
    )

if __name__ == "__main__":
    try:
        print("ByteRacer starting...")
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
    finally:
        # Clean up
        Vilib.camera_close()
        px.forward(0)
        px.set_dir_servo_angle(0)
        px.set_cam_pan_angle(0)
        px.set_cam_tilt_angle(0)
        print("ByteRacer offline.")
