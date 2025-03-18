import type { ServerWebSocket } from 'bun';
import { Hono } from 'hono';
import { createBunWebSocket } from 'hono/bun';

const app = new Hono();

const { upgradeWebSocket, websocket } =
  createBunWebSocket<ServerWebSocket>()

const cars = new Map<string, Car>()

type Car = {
  id: string;
}

type WebSocketEventName = "ping" | "pong" | "car_ready"

type WebSocketEvent = {
  name: WebSocketEventName,
  data: any
  createdAt: number
}

app.get(
  '/ws',
  upgradeWebSocket((c) => {
    return {
      onMessage(message, ws) {
        const event = JSON.parse(message.data.toString()) as WebSocketEvent
        console.table(event)

        switch (event.name) {
          case "car_ready":
            console.log("Car ready")
            cars.set(event.data.id, { id: event.data.id })
            break;
          case "ping":
            ws.send(JSON.stringify({
              name: 'pong',
              data: {},
              createdAt: event.createdAt
            }))
            break;
          default:
            break;
        }
      },
      onClose: () => {
        console.log('Connection closed')
      },
    }
  })
)

export default {
  fetch: app.fetch,
  websocket,
}