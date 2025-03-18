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

type WebSocketEventName = "ping" | "pong" | "car_ready" | "gamepad_input" | "client_register";

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
          // console.table({
          //   type: client.type,
          //   id: client.id,
          //   data: event.data
          // });
          console.log(message);
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

app.get("/stats", (c) => {
  return c.json({
    cars: Array.from(cars.keys()),
    controllers: controllers.size,
    viewers: viewers.size,
    totalClients: allClients.size
  });
});

export default {
  fetch: app.fetch,
  port: 3001,
  websocket: wsHandlers
};