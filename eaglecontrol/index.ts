import type { ServerWebSocket } from "bun";
import { Hono } from "hono";
import { createBunWebSocket } from "hono/bun";

const app = new Hono();

const { upgradeWebSocket, websocket } = createBunWebSocket<ServerWebSocket>();

const cars = new Map<string, Car>();
const clients = new Map<string, any>();

type Car = {
  id: string;
  socket: any;
};

type WebSocketEventName = "ping" | "pong" | "car_ready" | "gamepad_input";

type WebSocketEvent = {
  name: WebSocketEventName;
  data: any;
  createdAt: number;
};

function broadcast(event: any) {
  for (const socket of clients.values()) {
    socket.send(event);
  }
}

app.get(
  "/ws",
  upgradeWebSocket((c) => {
    return {
      onOpen(ws) {
        const uuid = "1";
        clients.set(uuid, ws);
        console.log("Client connected");
      },
      onMessage(message, ws) {
        const event = JSON.parse(message.data.toString()) as WebSocketEvent;

        switch (event.name) {
          case "car_ready":
            console.log("Car ready");
            cars.set(event.data.id, { id: event.data.id });

            console.log({
              event,
            });

            break;

          case "gamepad_input":
            console.log("Receiving gamepad_input");

            console.log({
              event,
            });
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

            console.log({
              event,
            });

            break;
          default:
            console.log({
              event,
            });
            break;
        }
      },
      onClose: () => {
        console.log("Connection closed");
      },
    };
  })
);

export default {
  fetch: app.fetch,
  websocket,
};
