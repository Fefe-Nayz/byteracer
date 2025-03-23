"use client";
import { useGamepadContext } from "@/contexts/GamepadContext";
import { useEffect, useRef, useState, useCallback } from "react";
import { Card } from "./ui/card";
import { trackWsMessage, trackWsConnection, logError } from "./DebugState";
import { ActionKey, ActionInfo } from "@/hooks/useGamepad"; // Add ActionInfo import

type GamepadStateValue = boolean | string | number;

export default function WebSocketStatus() {
  const {
    isActionActive,
    getAxisValueForAction,
    selectedGamepadId,
    mappings,
    ACTION_GROUPS,
    ACTIONS, // Add ACTIONS from context
  } = useGamepadContext();

  // Store function references in refs to avoid dependency issues
  const functionsRef = useRef({
    isActionActive,
    getAxisValueForAction,
    ACTION_GROUPS,
    ACTIONS, // Add ACTIONS to the ref
  });

  // Keep refs in sync with the latest functions
  useEffect(() => {
    functionsRef.current = {
      isActionActive,
      getAxisValueForAction,
      ACTION_GROUPS,
      ACTIONS, // Update ACTIONS in ref when it changes
    };
  }, [isActionActive, getAxisValueForAction, ACTION_GROUPS, ACTIONS]);

  const [status, setStatus] = useState<
    "connecting" | "connected" | "disconnected"
  >("connecting");
  const [pingTime, setPingTime] = useState<number | null>(null);
  const [socket, setSocket] = useState<WebSocket | null>(null);
  const [reconnectTrigger, setReconnectTrigger] = useState(0); // Add reconnect counter
  const pingTimestampRef = useRef<number>(0);
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Event listeners for debug controls
  useEffect(() => {
    const handleReconnect = () => {
      console.log("Reconnecting WebSocket...");
      if (socket) {
        if (
          socket.readyState === WebSocket.OPEN ||
          socket.readyState === WebSocket.CONNECTING
        ) {
          socket.close();
        }
      }
      // Increment the reconnect trigger to force the connection useEffect to run
      setReconnectTrigger((prev) => prev + 1);
    };

    const handleSendPing = () => {
      if (socket && socket.readyState === WebSocket.OPEN) {
        const pingData = {
          name: "ping",
          data: {
            sentAt: Date.now(),
            debug: true,
          },
          createdAt: Date.now(),
        };
        socket.send(JSON.stringify(pingData));
        trackWsMessage("sent", pingData);
      } else {
        logError("Cannot send ping", {
          reason: "Socket not connected",
          readyState: socket?.readyState,
        });
      }
    };

    const handleClearWsLogs = () => {
      // This will reset the lastWsSent and lastWsReceived in DebugState.tsx
      trackWsMessage("sent", null);
      trackWsMessage("received", null);
      // Force a re-render
      setStatus((prev) => (prev === "connected" ? "connected" : prev));
    };

    window.addEventListener("debug:reconnect-ws", handleReconnect);
    window.addEventListener("debug:send-ping", handleSendPing);
    window.addEventListener("debug:clear-ws-logs", handleClearWsLogs);

    return () => {
      window.removeEventListener("debug:reconnect-ws", handleReconnect);
      window.removeEventListener("debug:send-ping", handleSendPing);
      window.removeEventListener("debug:clear-ws-logs", handleClearWsLogs);
    };
  }, [socket]);

  // WebSocket connection effect - now depends on reconnectTrigger
  useEffect(() => {
    // Clean up any existing socket first
    if (socket) {
      if (
        socket.readyState === WebSocket.OPEN ||
        socket.readyState === WebSocket.CONNECTING
      ) {
        socket.close();
      }
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current);
        pingIntervalRef.current = null;
      }
    }

    // Get the hostname dynamically from current window location
    const hostname = window.location.hostname;
    console.log(
      `Connecting to WebSocket at ${hostname}:3001 (attempt #${reconnectTrigger})...`
    );
    setStatus("connecting");

    // Connect to websocket using dynamic hostname
    const ws = new WebSocket(`ws://${hostname}:3001/ws`);
    setSocket(ws);

    ws.onopen = () => {
      console.log("Connected to gamepad server");
      setStatus("connected");

      // Track connection for debug state
      trackWsConnection("connect");

      // Register as controller
      const registerData = {
        name: "client_register",
        data: {
          type: "controller",
          id: `controller-${Math.random().toString(36).substring(2, 9)}`,
        },
        createdAt: Date.now(),
      };

      ws.send(JSON.stringify(registerData));

      // Track message for debug
      trackWsMessage("sent", registerData);

      // Only start ping loop after connection is established
      pingIntervalRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          const pingData = {
            name: "ping",
            data: {
              sentAt: Date.now(),
            },
            createdAt: Date.now(),
          };

          ws.send(JSON.stringify(pingData));

          // Track ping for debug
          trackWsMessage("sent", pingData);
        }
      }, 500);
    };

    ws.onclose = () => {
      console.log("Disconnected from gamepad server");
      setStatus("disconnected");

      // Track disconnection for debug state
      trackWsConnection("disconnect");

      // Clear ping interval if connection closes
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current);
        pingIntervalRef.current = null;
      }
    };

    ws.onerror = (error) => {
      console.error("WebSocket error:", error);
      setStatus("disconnected");

      // Log error for debug state
      logError("WebSocket connection error", {
        message: "Connection error",
        errorType: error.type,
      });
    };

    ws.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data);

        // Track received message for debug
        trackWsMessage("received", event);

        if (event.name === "pong") {
          // Calculate round-trip time in milliseconds
          const now = Date.now();
          const latency = now - event.data.sentAt;
          setPingTime(latency);
        }
      } catch (e) {
        console.error("Error parsing websocket message:", e);
        logError("Error parsing WebSocket message", {
          error: e,
          rawMessage: message.data,
        });
      }
    };

    return () => {
      // Clean up when effect runs again or component unmounts
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current);
        pingIntervalRef.current = null;
      }
      if (
        ws.readyState === WebSocket.OPEN ||
        ws.readyState === WebSocket.CONNECTING
      ) {
        ws.close();
      }
    };
  }, [reconnectTrigger]); // Add reconnectTrigger and socket dependency

  // Wrap computeGamepadState in useCallback to prevent recreation on every render
  const computeGamepadState = useCallback(() => {
    const { isActionActive, getAxisValueForAction, ACTION_GROUPS, ACTIONS } =
      functionsRef.current;

    const gamepadState: Record<string, GamepadStateValue> = {};
    const processedActions = new Set<ActionKey>(); // Track which actions we've already processed

    // Process each action group to create a combined value
    ACTION_GROUPS.forEach((group) => {
      // Only process groups with exactly 2 opposing actions (like forward/backward)
      if (group.actions.length === 2) {
        const [action1, action2] = group.actions;

        // Get values for both actions in the group
        const value1 = getActionValue(action1);
        const value2 = getActionValue(action2);

        // Combine the values (positive - negative)
        gamepadState[group.key] = (value1 - value2).toFixed(2);

        // Mark these actions as processed
        processedActions.add(action1);
        processedActions.add(action2);
      } else {
        // For groups with different number of actions, process individually
        group.actions.forEach((action) => {
          processAction(action);
          processedActions.add(action);
        });
      }
    });

    // Now process any remaining actions that weren't part of a group
    ACTIONS.forEach((actionInfo: ActionInfo) => {
      if (!processedActions.has(actionInfo.key)) {
        processAction(actionInfo.key);
      }
    });

    // Function to process an individual action and add it to gamepadState
    function processAction(action: ActionKey) {
      const mapping = mappings[action];
      if (!mapping || mapping.index === -1) return;

      const actionInfo = ACTIONS.find((a: ActionInfo) => a.key === action);
      if (!actionInfo) return;

      // Handle actions based on their type
      if (
        actionInfo.type === "button" ||
        (actionInfo.type === "both" && mapping.type === "button")
      ) {
        // For button actions (or "both" mapped to button)
        gamepadState[action] = isActionActive(action);
      } else if (
        actionInfo.type === "axis" ||
        (actionInfo.type === "both" && mapping.type === "axis")
      ) {
        // For axis actions (or "both" mapped to axis)
        const value = getAxisValueForAction(action);
        if (value !== undefined) {
          gamepadState[action] = value.toFixed(2);
        }
      }
    }

    // Helper function to get normalized value for an action
    function getActionValue(action: ActionKey): number {
      const mapping = mappings[action];

      if (!mapping || mapping.index === -1) {
        return 0;
      }

      if (mapping.type === "button") {
        return isActionActive(action) ? 1 : 0;
      }

      if (mapping.type === "axis") {
        return getAxisValueForAction(action) ?? 0;
      }

      return 0;
    }

    return gamepadState;
  }, [mappings]);

  // Send gamepad state periodically
  useEffect(() => {
    // Only send data if connected to WebSocket AND have a selected gamepad
    if (!socket || status !== "connected" || !selectedGamepadId) return;

    const interval = setInterval(() => {
      // Check connection state before sending
      if (socket.readyState === WebSocket.OPEN) {
        pingTimestampRef.current = Date.now();

        // Get the comprehensive gamepad state
        const gamepadState = computeGamepadState();

        const message = {
          name: "gamepad_input",
          data: gamepadState,
          createdAt: pingTimestampRef.current,
        };

        socket.send(JSON.stringify(message));
        trackWsMessage("sent", message);
      }
    }, 50); // Send updates at 20 Hz

    return () => clearInterval(interval);
  }, [socket, status, selectedGamepadId, computeGamepadState]);

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
