# from picarx import Picarx
import time
import asyncio
import websockets

SERVER_HOST = "127.0.0.1:3000"

# Handle websocket
async def connect_to_websocket(url):
  async with websockets.connect(url) as websocket:
    print("Connected to server!")
    await websocket.send("Hello server!")
    while True:
      message = await websocket.recv()
      on_message(message)

# Handle message
def on_message(message):
  print(f"Received message: {message}")

if __name__ == "__main__":
  # try:
      # px = Picarx()
      url = f"ws://{SERVER_HOST}"
      asyncio.get_event_loop().run_until_complete(connect_to_websocket(url))
      print("ByteRacer online and ready!")
    # finally:
    #   px.forward(0)