import type { ServerWebSocket } from 'bun';
import { Hono } from 'hono';
import { createBunWebSocket } from 'hono/bun';

const app = new Hono();

const { upgradeWebSocket, websocket } =
  createBunWebSocket<ServerWebSocket>()

type WebSocketEvent = {
  name: string
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

        ws.send(JSON.stringify({ 
          name: 'pong',
          data: {},  
          createdAt: event.createdAt
        }))
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