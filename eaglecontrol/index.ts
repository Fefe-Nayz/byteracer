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
  | "sensor_data"         // For receiving sensor data
  | "camera_status"       // For receiving camera status
  | "speak_text"          // For sending text to be spoken
  | "play_sound"          // For sending a sound to be played
  | "gpt_command"         // For sending GPT commands
  | "gpt_response"        // For receiving GPT responses
  | "network_scan"        // For requesting network scan
  | "network_list"        // For receiving network list
  | "network_update";     // For updating network settings

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
          // No logging to avoid console spam
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

        // GPT commands
        case "gpt_command":
          console.log(`GPT command: ${event.data.prompt}`);
          // Forward to all cars
          broadcastToType(message, "car", ws);
          break;

        // GPT responses
        case "gpt_response":
          console.log("GPT response received");
          // Forward to all controllers and viewers
          broadcastToType(message, "controller", ws);
          broadcastToType(message, "viewer", ws);
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