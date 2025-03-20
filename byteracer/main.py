# from picarx import Picarx
import time
import asyncio
import websockets
import json
from vilib import Vilib
from picarx import Picarx

SERVER_HOST = "127.0.0.1:3001"

px = Picarx()

# Handle websocket
async def connect_to_websocket(url):
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

# Handle message
def on_message(message):
    try:
        data = json.loads(message)
        if data["name"] == "welcome":
            print(f"Received welcome message, client ID: {data['data']['clientId']}")
        elif data["name"] == "gamepad_input":
            print(f"Received gamepad input: {data['data']}")

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

async def main():
    Vilib.camera_start(vflip=False, hflip=False)
    Vilib.display(local=True, web=True)
    
    url = f"ws://{SERVER_HOST}/ws"  # Note the /ws path added
    print(f"Connecting to {url}...")
    await connect_to_websocket(url)

if __name__ == "__main__":
    try:
        # px = Picarx()
        print("ByteRacer starting...")
        asyncio.run(main())  # Modern way to run asyncio
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
