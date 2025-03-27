"use client";
import { useGamepadContext } from "@/contexts/GamepadContext";
import { useEffect, useRef, useState, useCallback } from "react";
import { Card } from "./ui/card";
import { trackWsMessage, trackWsConnection, logError } from "./DebugState";
import { ActionKey, ActionInfo } from "@/hooks/useGamepad";
import { AlertTriangle } from "lucide-react";

type GamepadStateValue = boolean | string | number;

export default function WebSocketStatus() {
  const {
    isActionActive,
    getAxisValueForAction,
    selectedGamepadId,
    mappings,
    ACTION_GROUPS,
    ACTIONS,
  } = useGamepadContext();

  const functionsRef = useRef({
    isActionActive,
    getAxisValueForAction,
    ACTION_GROUPS,
    ACTIONS,
  });

  useEffect(() => {
    functionsRef.current = {
      isActionActive,
      getAxisValueForAction,
      ACTION_GROUPS,
      ACTIONS,
    };
  }, [isActionActive, getAxisValueForAction, ACTION_GROUPS, ACTIONS]);

  const [status, setStatus] = useState<
    "connecting" | "connected" | "disconnected"
  >("connecting");
  const [pingTime, setPingTime] = useState<number | null>(null);
  const [socket, setSocket] = useState<WebSocket | null>(null);
  const [reconnectTrigger, setReconnectTrigger] = useState(0);
  const pingTimestampRef = useRef<number>(0);
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null);

  const [batteryLevel, setBatteryLevel] = useState<number | null>(null);
  const [customWsUrl, setCustomWsUrl] = useState<string | null>(null);
  const [customCameraUrl, setCustomCameraUrl] = useState<string | null>(null);

  const [cameraStatus, setCameraStatus] = useState<{
    status: "normal" | "restarted" | "error";
    message: string;
  }>({ status: "normal", message: "" });

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
      trackWsMessage("sent", null);
      trackWsMessage("received", null);
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

  // Handle URL updates from settings
  useEffect(() => {
    const handleUrlUpdate = (e: CustomEvent) => {
      setCustomWsUrl(e.detail.wsUrl);
      setCustomCameraUrl(e.detail.cameraUrl);
      console.log("URL settings updated:", e.detail);
    };
    window.addEventListener(
      "debug:update-urls",
      handleUrlUpdate as EventListener
    );

    const savedWsUrl = localStorage.getItem("debug_ws_url");
    const savedCameraUrl = localStorage.getItem("debug_camera_url");

    if (savedWsUrl) setCustomWsUrl(savedWsUrl);
    if (savedCameraUrl) setCustomCameraUrl(savedCameraUrl);

    return () => {
      window.removeEventListener(
        "debug:update-urls",
        handleUrlUpdate as EventListener
      );
    };
  }, []);

  // Handle robot commands
  useEffect(() => {
    const handleCommand = (e: CustomEvent) => {
      const { command, data } = e.detail;
      if (socket && socket.readyState === WebSocket.OPEN) {
        const commandData = {
          name: "robot_command",
          data: {
            command,
            data: data || {},
            timestamp: Date.now(),
          },
          createdAt: Date.now(),
        };
        socket.send(JSON.stringify(commandData));
        trackWsMessage("sent", commandData);
        console.log(`Robot command sent: ${command}`, data || {});
      } else {
        logError("Cannot send robot command", {
          reason: "Socket not connected",
          command,
          readyState: socket?.readyState,
        });
      }
    };

    const handleBatteryRequest = () => {
      if (socket && socket.readyState === WebSocket.OPEN) {
        const batteryRequestData = {
          name: "battery_request",
          data: { timestamp: Date.now() },
          createdAt: Date.now(),
        };
        socket.send(JSON.stringify(batteryRequestData));
        trackWsMessage("sent", batteryRequestData);
      } else {
        const dummyLevel = Math.round(65 + Math.random() * 25);
        setBatteryLevel(dummyLevel);
        window.dispatchEvent(
          new CustomEvent("debug:battery-update", {
            detail: { level: dummyLevel },
          })
        );
      }
    };

    const handleTabChange = (e: CustomEvent) => {
      if (e.detail.tab === "settings") {
        handleBatteryRequest();
      }
    };

    window.addEventListener(
      "debug:send-robot-command",
      handleCommand as EventListener
    );
    window.addEventListener(
      "debug:request-battery",
      handleBatteryRequest as EventListener
    );
    window.addEventListener(
      "debug:tab-change",
      handleTabChange as EventListener
    );

    return () => {
      window.removeEventListener(
        "debug:send-robot-command",
        handleCommand as EventListener
      );
      window.removeEventListener(
        "debug:request-battery",
        handleBatteryRequest as EventListener
      );
      window.removeEventListener(
        "debug:tab-change",
        handleTabChange as EventListener
      );
    };
  }, [socket]);

  // Connect or reconnect to WS
  useEffect(() => {
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

    let wsUrl;
    if (customWsUrl && customWsUrl.trim() !== "") {
      wsUrl = customWsUrl;
    } else {
      const hostname = window.location.hostname;
      wsUrl = `ws://${hostname}:3001/ws`;
    }
    console.log(
      `Connecting to WebSocket at ${wsUrl} (attempt #${reconnectTrigger})...`
    );

    setStatus("connecting");
    const ws = new WebSocket(wsUrl);
    setSocket(ws);

    ws.onopen = () => {
      console.log("Connected to gamepad server");
      setStatus("connected");
      trackWsConnection("connect");

      setCameraStatus({ status: "normal", message: "" });

      const registerData = {
        name: "client_register",
        data: {
          type: "controller",
          id: `controller-${Math.random().toString(36).substring(2, 9)}`,
        },
        createdAt: Date.now(),
      };
      ws.send(JSON.stringify(registerData));
      trackWsMessage("sent", registerData);

      pingIntervalRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          const pingData = {
            name: "ping",
            data: { sentAt: Date.now() },
            createdAt: Date.now(),
          };
          ws.send(JSON.stringify(pingData));
          trackWsMessage("sent", pingData);
        }
      }, 500);
    };

    ws.onclose = () => {
      console.log("Disconnected from gamepad server");
      setStatus("disconnected");
      trackWsConnection("disconnect");
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current);
        pingIntervalRef.current = null;
      }
    };

    ws.onerror = (error) => {
      console.error("WebSocket error:", error);
      setStatus("disconnected");
      logError("WebSocket connection error", {
        message: "Connection error",
        errorType: error.type,
      });
    };

    ws.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data);
        trackWsMessage("received", event);

        if (event.name === "pong") {
          const now = Date.now();
          const latency = now - event.data.sentAt;
          setPingTime(latency);
        } else if (event.name === "battery_info") {
          const level = event.data.level;
          setBatteryLevel(level);
          window.dispatchEvent(
            new CustomEvent("debug:battery-update", {
              detail: { level },
            })
          );
        } else if (event.name === "camera_status") {
          setCameraStatus({
            status: event.data.status as "restarted" | "error",
            message: event.data.message,
          });
          window.dispatchEvent(
            new CustomEvent("debug:camera-status", {
              detail: {
                status: event.data.status,
                message: event.data.message,
              },
            })
          );
        } else if (event.name === "command_response") {
          window.dispatchEvent(
            new CustomEvent("debug:command-response", {
              detail: event.data,
            })
          );
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
  }, [reconnectTrigger, customWsUrl]);

  // Send gamepad state periodically
  const computeGamepadState = useCallback(() => {
    const { isActionActive, getAxisValueForAction, ACTION_GROUPS, ACTIONS } =
      functionsRef.current;
    const gamepadState: Record<string, GamepadStateValue> = {};
    const processedActions = new Set<ActionKey>();

    ACTION_GROUPS.forEach((group) => {
      if (group.actions.length === 2) {
        const [action1, action2] = group.actions;
        const value1 = getActionValue(action1);
        const value2 = getActionValue(action2);
        gamepadState[group.key] = (value1 - value2).toFixed(2);
        processedActions.add(action1);
        processedActions.add(action2);
      } else {
        group.actions.forEach((action) => {
          processAction(action);
          processedActions.add(action);
        });
      }
    });

    ACTIONS.forEach((actionInfo: ActionInfo) => {
      if (!processedActions.has(actionInfo.key)) {
        processAction(actionInfo.key);
      }
    });

    function processAction(action: ActionKey) {
      const mapping = mappings[action];
      if (!mapping || mapping.index === -1) return;

      const actionInfo = ACTIONS.find((a: ActionInfo) => a.key === action);
      if (!actionInfo) return;

      if (
        actionInfo.type === "button" ||
        (actionInfo.type === "both" && mapping.type === "button")
      ) {
        gamepadState[action] = isActionActive(action);
      } else if (
        actionInfo.type === "axis" ||
        (actionInfo.type === "both" && mapping.type === "axis")
      ) {
        const value = getAxisValueForAction(action);
        if (value !== undefined) {
          gamepadState[action] = value.toFixed(2);
        }
      }
    }
    function getActionValue(action: ActionKey): number {
      const mapping = mappings[action];
      if (!mapping || mapping.index === -1) return 0;
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

  useEffect(() => {
    if (!socket || status !== "connected" || !selectedGamepadId) return;
    const interval = setInterval(() => {
      if (socket.readyState === WebSocket.OPEN) {
        pingTimestampRef.current = Date.now();
        const gamepadState = computeGamepadState();
        const message = {
          name: "gamepad_input",
          data: gamepadState,
          createdAt: pingTimestampRef.current,
        };
        socket.send(JSON.stringify(message));
        trackWsMessage("sent", message);
      }
    }, 50);
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

        {/* Camera error/warning */}
        {cameraStatus.status === "error" && (
          <div className="mt-2 p-2 bg-amber-100 dark:bg-amber-900/30 text-amber-800 dark:text-amber-200 rounded-md flex items-center">
            <AlertTriangle size={14} className="mr-2 flex-shrink-0" />
            <span className="text-xs">{cameraStatus.message}</span>
          </div>
        )}
      </div>
    </Card>
  );
}
