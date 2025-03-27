import { Hono } from "hono";
import type { ServerWebSocket } from "bun";
import { createBunWebSocket } from "hono/bun";

const app = new Hono();

type WSData = {
  id: string;
  type: "car" | "controller" | "viewer";
  connectedAt: number;
};
const { upgradeWebSocket } = createBunWebSocket<WSData>();

type Client = {
  ws: ServerWebSocket<WSData>;
  id: string;
  type: "car" | "controller" | "viewer";
  connectedAt: number;
};

const cars = new Map<string, Client>();
const controllers = new Map<string, Client>();
const viewers = new Map<string, Client>();
const allClients = new Map<ServerWebSocket<WSData>, Client>();

function broadcast(msg: string, exclude?: ServerWebSocket<WSData>) {
  for (const [ws, cl] of allClients.entries()) {
    if (exclude && ws === exclude) continue;
    try {
      ws.send(msg);
    } catch { }
  }
}

const wsHandlers = {
  open(ws: ServerWebSocket<WSData>) {
    const cid = crypto.randomUUID();
    ws.data = {
      id: cid,
      type: "viewer",
      connectedAt: Date.now(),
    };
    const client: Client = {
      ws,
      id: cid,
      type: "viewer",
      connectedAt: Date.now(),
    };
    allClients.set(ws, client);
    viewers.set(cid, client);
    console.log("New client:", cid);

    ws.send(
      JSON.stringify({
        name: "welcome",
        data: { clientId: cid },
        createdAt: Date.now(),
      })
    );
  },

  message(ws: ServerWebSocket<WSData>, message: string) {
    try {
      const event = JSON.parse(message);
      const cl = allClients.get(ws);
      if (!cl) return;
      switch (event.name) {
        case "client_register": {
          const { type, id } = event.data;
          if (type && ["car", "controller", "viewer"].includes(type)) {
            if (cl.type === "car") cars.delete(cl.id);
            else if (cl.type === "controller") controllers.delete(cl.id);
            else viewers.delete(cl.id);

            cl.type = type;
            cl.id = id || cl.id;
            ws.data.type = type;
            ws.data.id = id || cl.id;

            if (type === "car") cars.set(cl.id, cl);
            else if (type === "controller") controllers.set(cl.id, cl);
            else viewers.set(cl.id, cl);

            console.log(`Client ${cl.id} registered as ${type}`);
          }
          break;
        }
        case "car_ready": {
          console.log(`Car ready: ${event.data.id}`);
          if (cl.type !== "car") {
            viewers.delete(cl.id);
            controllers.delete(cl.id);
            cl.type = "car";
            cl.id = event.data.id;
            ws.data.type = "car";
            ws.data.id = event.data.id;
            cars.set(event.data.id, cl);
          }
          broadcast(message, ws);
          break;
        }
        case "gamepad_input": {
          // forward to cars
          for (const c of cars.values()) {
            c.ws.send(message);
          }
          // also forward to viewers
          for (const v of viewers.values()) {
            v.ws.send(message);
          }
          break;
        }
        case "robot_command": {
          // forward to cars
          for (const c of cars.values()) {
            c.ws.send(message);
          }
          
          break;
        }
        case "ping": {
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
        }
        case "battery_request": {
          // forward to cars
          for (const c of cars.values()) {
            c.ws.send(message);
          }
          break;
        }
        case "sensor_update": {
          // from car => pass to controllers & viewers
          for (const ctrl of controllers.values()) {
            ctrl.ws.send(message);
          }
          for (const vw of viewers.values()) {
            vw.ws.send(message);
          }
          break;
        }
        case "camera_status": {
          // from car => pass to controllers/viewers
          for (const ctrl of controllers.values()) {
            ctrl.ws.send(message);
          }
          for (const vw of viewers.values()) {
            vw.ws.send(message);
          }
          break;
        }
        case "command_response": {
          // from car => forward to controllers/viewers
          for (const ctrl of controllers.values()) {
            ctrl.ws.send(message);
          }
          for (const vw of viewers.values()) {
            vw.ws.send(message);
          }
          break;
        }
        default:
          console.log("Unknown event:", event.name);
      }
    } catch (e) {
      console.error("WS parse error", e);
    }
  },

  close(ws: ServerWebSocket<WSData>) {
    const cl = allClients.get(ws);
    if (cl) {
      console.log(`Client disconnected: ${cl.id} (${cl.type})`);
      allClients.delete(ws);
      if (cl.type === "car") cars.delete(cl.id);
      else if (cl.type === "controller") controllers.delete(cl.id);
      else viewers.delete(cl.id);
      broadcast(
        JSON.stringify({
          name: "client_disconnected",
          data: { id: cl.id, type: cl.type },
          createdAt: Date.now(),
        })
      );
    }
  },
};

app.get("/ws", upgradeWebSocket((_c) => wsHandlers));

app.get("/stats", (c) => {
  return c.json({
    cars: Array.from(cars.keys()),
    controllers: Array.from(controllers.keys()),
    viewers: Array.from(viewers.keys()),
    totalClients: allClients.size,
    lastUpdated: new Date().toISOString(),
  });
});

export default {
  fetch: app.fetch,
  port: 3001,
  websocket: wsHandlers,
};
