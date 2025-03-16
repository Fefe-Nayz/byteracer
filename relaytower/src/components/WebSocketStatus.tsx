"use client";
import { useEffect, useState, useRef } from "react";
import { useGamepadContext } from "@/contexts/GamepadContext";
import { Card } from "./ui/card";

export default function WebSocketStatus() {
  const [status, setStatus] = useState<
    "connecting" | "connected" | "disconnected"
  >("disconnected");
  const [pingTime, setPingTime] = useState<number | null>(null);
  const [socket, setSocket] = useState<WebSocket | null>(null);
  const pingTimestampRef = useRef<number>(0);
  const { isActionActive, getAxisValueForAction, selectedGamepadId } = useGamepadContext();

  useEffect(() => {
    // Connect to websocket
    const ws = new WebSocket("ws://localhost:3000/ws");

    ws.onopen = () => {
      console.log("Connected to gamepad server");
      setStatus("connected");
    };

    ws.onclose = () => {
      console.log("Disconnected from gamepad server");
      setStatus("disconnected");
    };

    ws.onerror = (error) => {
      console.error("WebSocket error:", error);
      setStatus("disconnected");
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.name === "pong") {
          // Calculate round-trip time in milliseconds
          const now = Date.now();
          const pingMs = now - pingTimestampRef.current;
          setPingTime(pingMs);
        }
      } catch (e) {
        console.error("Error parsing websocket message:", e);
      }
    };
    setSocket(ws);

    return () => {
      ws.close();
    };
  }, []);

  // Send gamepad state periodically
  useEffect(() => {
    // Only send data if connected to WebSocket AND have a selected gamepad
    if (!socket || status !== "connected" || !selectedGamepadId) return;
    
    const interval = setInterval(() => {
      pingTimestampRef.current = Date.now();
      
      // Send the current gamepad state
      const gamepadState = {
        accelerate: isActionActive("accelerate"),
        brake: isActionActive("brake"),
        turn: getAxisValueForAction("turn") ?? 0,
        turnCameraX: getAxisValueForAction("turnCameraX") ?? 0,
        turnCameraY: getAxisValueForAction("turnCameraY") ?? 0,
      };
      
      socket.send(
        JSON.stringify({
          type: "gamepadState",
          data: gamepadState,
          createdAt: pingTimestampRef.current,
        })
      );
    }, 30); // 20 updates per second
    
    return () => clearInterval(interval);
  }, [socket, status, isActionActive, getAxisValueForAction, selectedGamepadId]);

  return (
    <Card className="p-4">
      <div>
        <div className="flex items-center justify-between">
          <h3 className="font-bold">Server Connection</h3>
          <div className="flex items-center">
            <div
              className={`w-3 h-3 rounded-full mr-2 ${
                status === "connected"
                  ? "bg-green-500"
                  : status === "connecting"
                  ? "bg-yellow-500"
                  : "bg-red-500"
              }`}
            ></div>
            <span className="text-sm">
              {status === "connected"
                ? "Connected"
                : status === "connecting"
                ? "Connecting..."
                : "Disconnected"}
            </span>
          </div>
        </div>
        {pingTime !== null && (
          <p className="text-xs text-gray-500">Ping: {pingTime} ms</p>
        )}
      </div>
    </Card>
  );
}
