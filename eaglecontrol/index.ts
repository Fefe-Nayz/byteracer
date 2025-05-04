import { Hono } from "hono";
import type { ServerWebSocket } from "bun";
import { createBunWebSocket } from "hono/bun";

const app = new Hono();

// Define data types for WebSocket
type WSData = {
  id: string;
  type: "car" | "controller" | "viewer";
  connectedAt: number;
};

// Create the WebSocket handler with proper type
const { upgradeWebSocket } = createBunWebSocket<WSData>();

// Store all connected clients with their roles
type Client = {
  ws: ServerWebSocket<WSData>;
  id: string;
  type: "car" | "controller" | "viewer";
  connectedAt: number;
};

// Maps to store different types of connections
const cars = new Map<string, Client>();
const controllers = new Map<string, Client>();
const viewers = new Map<string, Client>();
const allClients = new Map<ServerWebSocket<WSData>, Client>();

// Update WebSocketEventName to include the new message types
type WebSocketEventName =
  | "ping"
  | "pong"
  | "car_ready"
  | "gamepad_input"
  | "client_register"
  | "robot_command"       // For sending commands to the robot
  | "command_response"    // For receiving command responses
  | "battery_request"     // For requesting battery level
  | "battery_info"        // For receiving battery information
  | "settings"            // For receiving settings from the robot
  | "settings_update"     // For sending settings changes to the robot
  | "reset_settings"      // For resetting settings to defaults
  | "sensor_data"         // For receiving sensor data
  | "camera_status"       // For receiving camera status
  | "speak_text"          // For sending text to be spoken
  | "play_sound"          // For sending a sound to be played
  | "stop_sound"          // For stopping all currently playing sounds
  | "stop_tts"            // For stopping currently playing speech
  | "gpt_command"         // For sending GPT commands
  | "gpt_response"        // For receiving GPT responses
  | "gpt_status_update"   // For receiving GPT status updates
  | "cancel_gpt"          // For cancelling a GPT command
  | "create_thread"       // For creating a new GPT conversation thread
  | "network_scan"        // For requesting network scan
  | "network_list"        // For receiving network list
  | "network_update"      // For updating network settings
  | "audio_stream"        // For streaming audio data to the robot
  | "start_listening"      // For starting audio listening
  | "stop_listening"       // For stopping audio listening
  | "python_status_request" // For requesting Python connection status
  | "log_message"
  | "speech_recognition"
  | "start_calibration"
  | "stop_calibration"
  | "test_calibration";

type WebSocketEvent = {
  name: WebSocketEventName;
  data: any;
  createdAt: number;
};

// Broadcast function to send messages to clients
function broadcast(message: string, excludeWs?: ServerWebSocket<WSData>) {
  allClients.forEach((client, ws) => {
    if (excludeWs && ws === excludeWs) return;
    try {
      ws.send(message);
    } catch (err) {
      console.error(`Error broadcasting to client ${client.id}:`, err);
    }
  });
}

// Function to broadcast only to specific client types
function broadcastToType(message: string, clientType: "car" | "controller" | "viewer", excludeWs?: ServerWebSocket<WSData>) {
  const clientMap = clientType === "car" ? cars :
    clientType === "controller" ? controllers : viewers;

  clientMap.forEach((client) => {
    if (excludeWs && client.ws === excludeWs) return;
    try {
      client.ws.send(message);
    } catch (err) {
      console.error(`Error broadcasting to ${clientType} ${client.id}:`, err);
    }
  });
}

// Define WebSocket handlers
const wsHandlers = {
  open(ws: ServerWebSocket<WSData>) {
    const clientId = crypto.randomUUID();

    // Set data directly on WebSocket object
    ws.data = {
      id: clientId,
      type: "viewer",
      connectedAt: Date.now()
    };

    const client: Client = {
      ws,
      id: clientId,
      type: "viewer",
      connectedAt: Date.now()
    };

    allClients.set(ws, client);
    viewers.set(clientId, client);

    console.log(`New client connected: ${clientId}`);

    ws.send(JSON.stringify({
      name: "welcome",
      data: { clientId },
      createdAt: Date.now()
    }));
  },

  message(ws: ServerWebSocket<WSData>, message: string) {
    try {
      const event = JSON.parse(message) as WebSocketEvent;
      const client = allClients.get(ws);

      if (!client) {
        console.warn("Message received from unknown client");
        return;
      }

      switch (event.name) {
        case "client_register":
          const { type, id } = event.data;
          if (type && ["car", "controller", "viewer"].includes(type)) {
            if (client.type === "car") cars.delete(client.id);
            else if (client.type === "controller") controllers.delete(client.id);
            else viewers.delete(client.id);

            client.type = type;
            client.id = id || client.id;
            ws.data.type = type;
            ws.data.id = id || client.id;

            if (type === "car") cars.set(client.id, client);
            else if (type === "controller") controllers.set(client.id, client);
            else viewers.set(client.id, client);

            broadcastToType(message, "car", ws);

            console.log(`Client ${client.id} registered as ${type}`);
          }
          break;

        case "car_ready":
          console.log(`Car ready: ${event.data.id}`);
          if (client.type !== "car") {
            viewers.delete(client.id);
            controllers.delete(client.id);

            client.type = "car";
            client.id = event.data.id;
            ws.data.type = "car";
            ws.data.id = event.data.id;
            cars.set(event.data.id, client);
          }

          broadcastToType(message, "controller");
          break;

        case "gamepad_input":
          broadcastToType(message, "car", ws);
          broadcastToType(message, "viewer", ws);
          // Reduced logging frequency for gamepad inputs to avoid console spam
          break;

        case "ping":
          const sentAt = event.data.sentAt;
          ws.send(
            JSON.stringify({
              name: "pong",
              data: {
                sentAt,
              },
              createdAt: event.createdAt,
            })
          );
          break;

        // Robot commands
        case "robot_command":
          console.log(`Robot command received: ${event.data.command}`);
          // Forward command to all cars
          broadcastToType(message, "car", ws);
          break;

        // Battery requests
        case "battery_request":
          console.log("Battery level request received");
          // Forward the request to all cars
          broadcastToType(message, "car", ws);
          break;

        // Command responses
        case "command_response":
          console.log(`Command response: ${event.data.message}`);
          // Forward the response to all controllers and viewers
          broadcastToType(message, "controller", ws);
          broadcastToType(message, "viewer", ws);
          break;

        // Battery information
        case "battery_info":
          // Forward battery info to all controllers and viewers
          broadcastToType(message, "controller", ws);
          broadcastToType(message, "viewer", ws);
          break;

        // Sensor data
        case "sensor_data":
          // Forward sensor data to all controllers and viewers
          broadcastToType(message, "controller", ws);
          broadcastToType(message, "viewer", ws);
          break;

        // Camera status
        case "camera_status":
          console.log(`Camera status: ${event.data.state}`);
          // Forward camera status to all controllers and viewers
          broadcastToType(message, "controller", ws);
          broadcastToType(message, "viewer", ws);
          break;

        // Settings from robot
        case "settings":
          console.log("Settings received from: " + client.type);
          if (client.type === "car") {
            // Forward settings from car to all controllers and viewers
            broadcastToType(message, "controller", ws);
            broadcastToType(message, "viewer", ws);
          } else if (client.type === "controller" || client.type === "viewer") {
            // Forward settings request from controller/viewer to all cars
            console.log("Forwarding settings request to cars");
            broadcastToType(message, "car", ws);
          }
          break;

        // Settings updates from client
        case "settings_update":
          console.log("Settings update request received");
          // Forward settings update to all cars
          broadcastToType(message, "car", ws);
          break;

        // Reset settings
        case "reset_settings":
          console.log(`Settings reset request received for section: ${event.data.section || "all"}`);
          // Forward to all cars
          broadcastToType(message, "car", ws);
          break;

        // Text to speak
        case "speak_text":
          console.log(`Text to speak: ${event.data.text}`);
          // Forward to all cars
          broadcastToType(message, "car", ws);
          break;

        // Sound to play
        case "play_sound":
          console.log(`Sound to play: ${event.data.sound}`);
          // Forward to all cars
          broadcastToType(message, "car", ws);
          break;

        // Stop sound
        case "stop_sound":
          console.log("Stop sound request received");
          // Forward to all cars
          broadcastToType(message, "car", ws);
          break;

        // Stop TTS
        case "stop_tts":
          console.log("Stop TTS request received");
          // Forward to all cars
          broadcastToType(message, "car", ws);
          break;

        // GPT commands
        case "gpt_command":
          console.log(`GPT command: ${event.data.prompt}`);
          // Forward to all cars
          broadcastToType(message, "car", ws);
          break;        // GPT responses
        case "gpt_response":
          console.log("GPT response received");
          // Forward to all controllers and viewers
          broadcastToType(message, "controller", ws);
          broadcastToType(message, "viewer", ws);
          break;

        // GPT status updates
        case "gpt_status_update":
          console.log(`GPT status update: ${event.data.status} - ${event.data.message}`);
          // Forward to all controllers and viewers
          broadcastToType(message, "controller", ws);
          broadcastToType(message, "viewer", ws);
          break;        // Cancel GPT command
        case "cancel_gpt":
          console.log("GPT command cancellation request received");
          // Forward to all cars
          broadcastToType(message, "car", ws);
          break;
          
        // Create new thread
        case "create_thread":
          console.log("New GPT thread request received");
          // Forward to all cars
          broadcastToType(message, "car", ws);
          break;

        // Network scan request
        case "network_scan":
          console.log("Network scan requested");
          // Forward to all cars
          broadcastToType(message, "car", ws);
          break;

        // Network list update
        case "network_list":
          console.log("Network list received");
          // Forward to all controllers and viewers
          broadcastToType(message, "controller", ws);
          broadcastToType(message, "viewer", ws);
          break;

        // Network settings update
        case "network_update":
          console.log(`Network update request: ${event.data.action}`);
          // Forward to all cars
          broadcastToType(message, "car", ws);
          break;

        // Existing cases ...
        case "audio_stream":
          console.log("Audio stream received");
          // Forward the audio stream from a controller to all connected cars
          if (client.type === "controller") {
            broadcastToType(message, "car", ws);
          }
          else if (client.type === "car") {
            broadcastToType(message, "controller", ws);
          }
          break;
        
        case "start_listening":
          console.log("Start listening command received");
          // Forward to all cars
          broadcastToType(message, "car", ws);
          break;

        case "stop_listening":
          console.log("Stop listening command received");
          // Forward to all cars
          broadcastToType(message, "car", ws);
          break;

        // Python status request
        case "python_status_request":
          console.log("Python connection status requested");
          
          // Check if there are any car clients connected
          const carsConnected = cars.size > 0;
          
          // Respond immediately with the current connection status
          ws.send(JSON.stringify({
            name: "python_status",
            data: {
              connected: carsConnected,
              timestamp: Date.now()
            },
            createdAt: Date.now()
          }));
          
          console.log(`Python connection status: ${carsConnected ? "Connected" : "Disconnected"}`);
          break;

        case "log_message":
          // Forward log messages to all controllers and viewers
          broadcastToType(message, "controller", ws);
          broadcastToType(message, "viewer", ws);
          break;
        
        case "speech_recognition":
          console.log("Speech recognition data received");
          // Forward speech recognition data to all controllers
          broadcastToType(message, "controller", ws);
          break;

        case "start_calibration":
          console.log("Start calibration command received");
          // Forward to all cars
          broadcastToType(message, "car", ws);
          break;

        case "stop_calibration":
          console.log("Stop calibration command received");
          // Forward to all cars
          broadcastToType(message, "car", ws);
          break;

        case "test_calibration":
          console.log("Test calibration command received");
          // Forward to all cars
          broadcastToType(message, "car", ws);
          break;

        default:
          console.log("Unknown event type:", event.name);
          console.log({ event });
          break;
      }
    } catch (err) {
      console.error("Error processing WebSocket message:", err);
    }
  },

  close(ws: ServerWebSocket<WSData>) {
    const client = allClients.get(ws);
    if (client) {
      console.log(`Client disconnected: ${client.id} (${client.type})`);

      allClients.delete(ws);
      if (client.type === "car") cars.delete(client.id);
      else if (client.type === "controller") controllers.delete(client.id);
      else viewers.delete(client.id);

      const disconnectMsg = JSON.stringify({
        name: "client_disconnected",
        data: { id: client.id, type: client.type },
        createdAt: Date.now()
      });
      broadcast(disconnectMsg);
    }
  }
};

// Define WebSocket route
app.get('/ws', upgradeWebSocket((_c) => wsHandlers));

// Enhanced stats endpoint to include active connections
app.get("/stats", (c) => {
  return c.json({
    cars: Array.from(cars.keys()),
    controllers: Array.from(controllers.keys()),
    viewers: Array.from(viewers.keys()),
    totalClients: allClients.size,
    lastUpdated: new Date().toISOString()
  });
});

export default {
  fetch: app.fetch,
  port: 3001,
  websocket: wsHandlers
};