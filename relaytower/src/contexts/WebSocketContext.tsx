"use client";
import { createContext, useContext, ReactNode, useState, useEffect, useRef, useCallback } from "react";
import { trackWsMessage, trackWsConnection, logError } from "@/components/DebugState";

// Define message types that match our WebSocket protocol
export type WebSocketMessageType =
  | "ping"
  | "pong"
  | "car_ready"
  | "gamepad_input"
  | "client_register"
  | "robot_command"
  | "command_response"
  | "battery_request"
  | "battery_info"
  | "settings"
  | "settings_update"
  | "sensor_data"
  | "camera_status"
  | "speak_text"
  | "play_sound"
  | "stop_sound"
  | "stop_tts"
  | "gpt_command"
  | "gpt_response"
  | "network_scan"
  | "network_list"
  | "network_update"
  | "audio_stream"
  | "python_status_request"
  | "python_status";
// Define WebSocket connection status type
export type WebSocketStatus = "connecting" | "connected" | "disconnected";

// Define robot command types
export type RobotCommand =
  | "restart_robot"
  | "stop_robot"
  | "restart_all_services"
  | "restart_websocket"
  | "restart_web_server"
  | "restart_python_service"
  | "restart_camera_feed"
  | "check_for_updates"
  | "emergency_stop"
  | "clear_emergency";

// Define network action types
export type NetworkAction =
  | "connect_wifi"
  | "create_ap"
  | "add_network"
  | "remove_network"
  | "update_ap_settings"
  | "connect_wifi_mode"

// Define network update data interface
export interface NetworkUpdateData {
  ssid?: string;
  password?: string;
  mode?: "wifi" | "ap";
  ap_name?: string;
  ap_password?: string;
  [key: string]: string | undefined;
}

// Define log message interface
export interface LogMessage {
  level: string;
  message: string;
  timestamp: number;
}

// Define sensor data interface
export interface SensorData {
  ultrasonicDistance: number;
  lineFollowLeft: number;
  lineFollowMiddle: number;
  lineFollowRight: number;
  emergencyState: string | null;
  batteryLevel: number;
  isCollisionAvoidanceActive: boolean;
  isEdgeDetectionActive: boolean;
  isAutoStopActive: boolean;
  isTrackingActive: boolean;
  isCircuitModeActive: boolean;
  isDemoModeActive: boolean;
  isNormalModeActive: boolean;
  isGptModeActive: boolean;
  clientConnected: boolean;
  lastClientActivity: number;
  speed: number;
  turn: number;
  acceleration: number;
  ramUsage: number;
  cpuUsage: number;
}

// Define camera status interface
export interface CameraStatus {
  state: string;
  error?: string;
  restart_attempts?: number;
  last_start_time?: number;
  settings?: {
    vflip: boolean;
    hflip: boolean;
    local: boolean;
    web: boolean;
    resolution: string;
  }
}

// Define settings interface
export interface RobotSettings {
  sound: {
    enabled: boolean;
    tts_enabled: boolean;
    tts_language: string;
    volume: number;
    sound_volume: number;
    driving_volume: number;
    alert_volume: number;
    custom_volume: number;
    voice_volume: number;
    tts_volume: number;
    user_tts_volume: number;
    tts_audio_gain: number;
    system_tts_volume: number;
    emergency_tts_volume: number;
  };
  camera: {
    vflip: boolean;
    hflip: boolean;
    local_display: boolean;
    web_display: boolean;
    camera_size: Array<number>;
  };
  safety: {
    collision_avoidance: boolean;
    edge_detection: boolean;
    auto_stop: boolean;
    collision_threshold: number;
    edge_threshold: number;
    client_timeout: number;
  };
  drive: {
    max_speed: number;
    max_turn_angle: number;
    acceleration_factor: number;
    enhanced_turning: boolean;
    turn_in_place: boolean;
  };
  modes: {
    normal_mode_enabled: boolean;
    tracking_enabled: boolean;
    circuit_mode_enabled: boolean;
    demo_mode_enabled: boolean;
  };
  github: {
    branch: string;
    repo_url: string;
    auto_update: boolean;
  };
  api: {
    openai_api_key: string;
  }
}

// Define command response interface
export interface CommandResponse {
  success: boolean;
  message: string;
}

// Define WebSocket context value interface
interface WebSocketContextValue {
  // Connection
  status: WebSocketStatus;
  pingTime: number | null;
  connect: () => void;
  disconnect: () => void;
  customWsUrl: string | null;
  setCustomWsUrl: (url: string | null) => void;
  customCameraUrl: string | null;
  setCustomCameraUrl: (url: string | null) => void;
  pythonStatus: "connected" | "disconnected" | "unknown";
  requestPythonStatus: () => void;

  // Data state
  batteryLevel: number | null;
  sensorData: SensorData | null;
  cameraStatus: CameraStatus | null;
  settings: RobotSettings | null;
  commandResponse: CommandResponse | null;
  logs: LogMessage[];
  clearLogs: () => void;

  // Commands
  sendGamepadState: (gamepadState: Record<string, boolean | string | number>) => void;
  sendRobotCommand: (command: RobotCommand) => void;
  requestBatteryLevel: () => void;
  requestSettings: () => void;
  updateSettings: (settings: Partial<RobotSettings>) => void;
  resetSettings: (section?: string) => void;
  speakText: (text: string, language: string) => void;
  playSound: (sound: string) => void;
  stopSound: () => void;
  stopTts: () => void;
  restartCameraFeed: () => void;
  scanNetworks: () => void;
  updateNetwork: (action: NetworkAction, data: NetworkUpdateData) => void;
  sendGptCommand: (prompt: string, useCamera: boolean) => void;
  sendAudioStream: (audioData: string) => void;
}

// Create context with default values
const WebSocketContext = createContext<WebSocketContextValue | undefined>(undefined);

// Provider component
export function WebSocketProvider({ children }: { children: ReactNode }) {
  // Connection state
  const [status, setStatus] = useState<WebSocketStatus>("connecting");
  const [socket, setSocket] = useState<WebSocket | null>(null);
  const [reconnectTrigger, setReconnectTrigger] = useState(0);
  const [pingTime, setPingTime] = useState<number | null>(null);
  const [customWsUrl, setCustomWsUrl] = useState<string | null>(null);
  const [customCameraUrl, setCustomCameraUrl] = useState<string | null>(null);

  // Add Python connection status state
  const [pythonStatus, setPythonStatus] = useState<"connected" | "disconnected" | "unknown">("unknown");

  // Data state
  const [batteryLevel, setBatteryLevel] = useState<number | null>(null);
  const [sensorData, setSensorData] = useState<SensorData | null>(null);
  const [cameraStatus, setCameraStatus] = useState<CameraStatus | null>(null);
  const [settings, setSettings] = useState<RobotSettings | null>(null);
  const [commandResponse, setCommandResponse] = useState<CommandResponse | null>(null);
  const [logs, setLogs] = useState<LogMessage[]>([]);

  // Function to clear logs
  const clearLogs = useCallback(() => {
    setLogs([]);
  }, []);

  // Refs
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const socketRef = useRef<WebSocket | null>(null);

  // Connect to WebSocket
  const connect = useCallback(() => {
    setReconnectTrigger(prev => prev + 1);
  }, []);

  // Disconnect from WebSocket
  const disconnect = useCallback(() => {
    if (socketRef.current) {
      if (socketRef.current.readyState === WebSocket.OPEN ||
        socketRef.current.readyState === WebSocket.CONNECTING) {
        socketRef.current.close();
      }
    }
  }, []);

  // WebSocket connection effect
  useEffect(() => {
    // Clean up any existing socket first
    if (socket) {
      if (socket.readyState === WebSocket.OPEN ||
        socket.readyState === WebSocket.CONNECTING) {
        socket.close();
      }
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current);
        pingIntervalRef.current = null;
      }
    }

    // Determine which WebSocket URL to use
    let wsUrl;
    if (customWsUrl && customWsUrl.trim() !== "") {
      wsUrl = customWsUrl;
    } else {
      const hostname = window.location.hostname;
      wsUrl = `ws://${hostname}:3001/ws`;
    }

    console.log(`Connecting to WebSocket at ${wsUrl} (attempt #${reconnectTrigger})...`);
    setStatus("connecting");

    // Connect to websocket
    const ws = new WebSocket(wsUrl);
    setSocket(ws);
    socketRef.current = ws;

    ws.onopen = () => {
      console.log("Connected to gamepad server");
      setStatus("connected");
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
      trackWsMessage("sent", registerData);

      // Request battery level immediately after connection
      requestBatteryLevel();

      // Request settings immediately after connection - directly send the request
      // instead of calling requestSettings() to avoid closure issues
      const settingsRequestData = {
        name: "settings",
        data: {
          timestamp: Date.now(),
        },
        createdAt: Date.now(),
      };

      ws.send(JSON.stringify(settingsRequestData));
      trackWsMessage("sent", settingsRequestData);
      console.log("Settings request sent directly after connection");

      // Start ping interval
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

        // Handle different message types
        switch (event.name) {
          case "pong":
            // Calculate round-trip time in milliseconds
            const now = Date.now();
            const latency = now - event.data.sentAt;
            setPingTime(latency);
            break;

          case "battery_info":
            setBatteryLevel(event.data.level);
            window.dispatchEvent(
              new CustomEvent("debug:battery-update", {
                detail: { level: event.data.level },
              })
            );
            break;

          case "sensor_data":
            setSensorData(event.data);
            break;

          case "camera_status":
            setCameraStatus(event.data);
            break;

          case "settings":
            if (event.data.settings) {
              setSettings(event.data.settings);
            }
            break;

          case "command_response":
            setCommandResponse(event.data);
            // Dispatch event for other components
            window.dispatchEvent(
              new CustomEvent("debug:command-response", {
                detail: event.data,
              })
            );
            break;

          case "network_list":
            // Dispatch event for network settings component
            window.dispatchEvent(
              new CustomEvent("debug:network-list", {
                detail: event.data,
              })
            );
            break;

          case "gpt_response":
            // Dispatch event for GPT response handler
            window.dispatchEvent(
              new CustomEvent("debug:gpt-response", {
                detail: event.data,
              })
            );
            break;

          case "log_message":
            // Add log message to the logs array (limit to most recent 500 logs)
            setLogs(prevLogs => {
              const newLogs = [...prevLogs, event.data];
              // Keep only the most recent 500 logs to avoid memory issues
              return newLogs.slice(-500);
            });
            break;

          case "python_status":
            setPythonStatus(event.data.connected ? "connected" : "disconnected");
            break;
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
      if (ws.readyState === WebSocket.OPEN ||
        ws.readyState === WebSocket.CONNECTING) {
        ws.close();
      }
    };
  }, [reconnectTrigger, customWsUrl]);

  // Load saved URLs on initial render
  useEffect(() => {
    const savedWsUrl = localStorage.getItem("debug_ws_url");
    const savedCameraUrl = localStorage.getItem("debug_camera_url");

    if (savedWsUrl) setCustomWsUrl(savedWsUrl);
    if (savedCameraUrl) setCustomCameraUrl(savedCameraUrl);
  }, []);

  // Save URLs when they change
  useEffect(() => {
    if (customWsUrl) {
      localStorage.setItem("debug_ws_url", customWsUrl);
    }
    if (customCameraUrl) {
      localStorage.setItem("debug_camera_url", customCameraUrl);
    }
  }, [customWsUrl, customCameraUrl]);

  // Function to send gamepad state
  const sendGamepadState = useCallback((gamepadState: Record<string, boolean | string | number>) => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      const message = {
        name: "gamepad_input",
        data: gamepadState,
        createdAt: Date.now(),
      };

      socket.send(JSON.stringify(message));
      trackWsMessage("sent", message);
    }
  }, [socket]);

  // Function to send robot commands
  const sendRobotCommand = useCallback((command: RobotCommand) => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      const commandData = {
        name: "robot_command",
        data: {
          command,
          timestamp: Date.now(),
        },
        createdAt: Date.now(),
      };

      socket.send(JSON.stringify(commandData));
      trackWsMessage("sent", commandData);
      console.log(`Robot command sent: ${command}`);
    } else {
      logError("Cannot send robot command", {
        reason: "Socket not connected",
        command,
        readyState: socket?.readyState,
      });
    }
  }, [socket]);

  // Function to request battery level
  const requestBatteryLevel = useCallback(() => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      const batteryRequestData = {
        name: "battery_request",
        data: {
          timestamp: Date.now(),
        },
        createdAt: Date.now(),
      };

      socket.send(JSON.stringify(batteryRequestData));
      trackWsMessage("sent", batteryRequestData);
    } else {
      // If not connected, use dummy data
      const dummyLevel = Math.round(65 + Math.random() * 25);
      setBatteryLevel(dummyLevel);

      window.dispatchEvent(
        new CustomEvent("debug:battery-update", {
          detail: { level: dummyLevel },
        })
      );
    }
  }, [socket]);

  // Function to request settings data
  const requestSettings = useCallback(() => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      const settingsRequestData = {
        name: "settings",
        data: {
          timestamp: Date.now(),
        },
        createdAt: Date.now(),
      };

      socket.send(JSON.stringify(settingsRequestData));
      trackWsMessage("sent", settingsRequestData);
      console.log("Settings request sent");
    } else {
      logError("Cannot send settings request", {
        reason: "Socket not connected",
        readyState: socket?.readyState,
      });
    }
  }, [socket]);

  // Function to update settings
  const updateSettings = useCallback((newSettings: Partial<RobotSettings>) => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      const settingsData = {
        name: "settings_update",
        data: {
          settings: newSettings,
          timestamp: Date.now(),
        },
        createdAt: Date.now(),
      };

      socket.send(JSON.stringify(settingsData));
      trackWsMessage("sent", settingsData);
      console.log("Settings update sent");
    } else {
      logError("Cannot send settings update", {
        reason: "Socket not connected",
        readyState: socket?.readyState,
      });
    }
  }, [socket]);

  // Function to reset settings
  const resetSettings = useCallback((section?: string) => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      const resetData = {
        name: "reset_settings",
        data: {
          section,
          timestamp: Date.now(),
        },
        createdAt: Date.now(),
      };

      socket.send(JSON.stringify(resetData));
      trackWsMessage("sent", resetData);
      console.log(`Settings reset sent for section: ${section}`);
    } else {
      logError("Cannot send settings reset", {
        reason: "Socket not connected",
        readyState: socket?.readyState,
      });
    }
  }, [socket]);

  // Function to send text to speak
  const speakText = useCallback((text: string, language: string) => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      const ttsData = {
        name: "speak_text",
        data: {
          text,
          language,
          timestamp: Date.now(),
        },
        createdAt: Date.now(),
      };

      socket.send(JSON.stringify(ttsData));
      trackWsMessage("sent", ttsData);
      console.log(`Text to speak sent: ${text}`);
    } else {
      logError("Cannot send text to speak", {
        reason: "Socket not connected",
        readyState: socket?.readyState,
      });
    }
  }, [socket]);

  // Function to play a sound
  const playSound = useCallback((sound: string) => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      const soundData = {
        name: "play_sound",
        data: {
          sound,
          timestamp: Date.now(),
        },
        createdAt: Date.now(),
      };

      socket.send(JSON.stringify(soundData));
      trackWsMessage("sent", soundData);
      console.log(`Sound to play sent: ${sound}`);
    } else {
      logError("Cannot send sound to play", {
        reason: "Socket not connected",
        readyState: socket?.readyState,
      });
    }
  }, [socket]);

  // Function to stop current sound playback
  const stopSound = useCallback(() => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      const stopSoundData = {
        name: "stop_sound",
        data: {
          timestamp: Date.now(),
        },
        createdAt: Date.now(),
      };

      socket.send(JSON.stringify(stopSoundData));
      trackWsMessage("sent", stopSoundData);
      console.log("Stop sound request sent");
    } else {
      logError("Cannot send stop sound request", {
        reason: "Socket not connected",
        readyState: socket?.readyState,
      });
    }
  }, [socket]);

  // Function to stop current TTS playback
  const stopTts = useCallback(() => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      const stopTtsData = {
        name: "stop_tts",
        data: {
          timestamp: Date.now(),
        },
        createdAt: Date.now(),
      };

      socket.send(JSON.stringify(stopTtsData));
      trackWsMessage("sent", stopTtsData);
      console.log("Stop TTS request sent");
    } else {
      logError("Cannot send stop TTS request", {
        reason: "Socket not connected",
        readyState: socket?.readyState,
      });
    }
  }, [socket]);

  // Function to restart camera feed
  const restartCameraFeed = useCallback(() => {
    sendRobotCommand("restart_camera_feed");
  }, [sendRobotCommand]);

  // Function to scan networks
  const scanNetworks = useCallback(() => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      const scanData = {
        name: "network_scan",
        data: {
          timestamp: Date.now(),
        },
        createdAt: Date.now(),
      };

      socket.send(JSON.stringify(scanData));
      trackWsMessage("sent", scanData);
      console.log("Network scan request sent");
    } else {
      logError("Cannot send network scan request", {
        reason: "Socket not connected",
        readyState: socket?.readyState,
      });
    }
  }, [socket]);

  // Function to update network settings
  const updateNetwork = useCallback((action: NetworkAction, data: NetworkUpdateData) => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      const networkData = {
        name: "network_update",
        data: {
          action,
          data,
          timestamp: Date.now(),
        },
        createdAt: Date.now(),
      };

      socket.send(JSON.stringify(networkData));
      trackWsMessage("sent", networkData);
      console.log(`Network update sent: ${action}`);
    } else {
      logError("Cannot send network update", {
        reason: "Socket not connected",
        readyState: socket?.readyState,
      });
    }
  }, [socket]);

  // Function to send GPT command
  const sendGptCommand = useCallback((prompt: string, useCamera: boolean) => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      const gptData = {
        name: "gpt_command",
        data: {
          prompt,
          useCamera,
          timestamp: Date.now(),
        },
        createdAt: Date.now(),
      };

      socket.send(JSON.stringify(gptData));
      trackWsMessage("sent", gptData);
      console.log(`GPT command sent: ${prompt}`);
    } else {
      logError("Cannot send GPT command", {
        reason: "Socket not connected",
        readyState: socket?.readyState,
      });
    }
  }, [socket]);

  // Function to send audio stream data
  const sendAudioStream = useCallback((audioData: string) => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      const message = {
        name: "audio_stream",
        data: {
          audio: audioData,
          timestamp: Date.now(),
        },
        createdAt: Date.now(),
      };
      socket.send(JSON.stringify(message));
      trackWsMessage("sent", message);
    } else {
      logError("Cannot send audio stream", {
        reason: "Socket not connected",
        readyState: socket?.readyState,
      });
    }
  }, [socket]);

  // Function to request Python connection status
  const requestPythonStatus = useCallback(() => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      const pythonStatusRequest = {
        name: "python_status_request",
        data: {
          timestamp: Date.now(),
        },
        createdAt: Date.now(),
      };

      socket.send(JSON.stringify(pythonStatusRequest));
      trackWsMessage("sent", pythonStatusRequest);
    } else {
      // If not connected to WebSocket, Python connection is definitely not available
      setPythonStatus("disconnected");
    }
  }, [socket]);

  // Combine all values and functions for the context
  const contextValue: WebSocketContextValue = {
    // Connection
    status,
    pingTime,
    connect,
    disconnect,
    customWsUrl,
    setCustomWsUrl,
    customCameraUrl,
    setCustomCameraUrl,
    pythonStatus,
    requestPythonStatus,

    // Data state
    batteryLevel,
    sensorData,
    cameraStatus,
    settings,
    commandResponse,
    logs,
    clearLogs,

    // Commands
    sendGamepadState,
    sendRobotCommand,
    requestBatteryLevel,
    requestSettings,
    updateSettings,
    resetSettings,
    speakText,
    playSound,
    stopSound,
    stopTts,
    restartCameraFeed,
    scanNetworks,
    updateNetwork,
    sendGptCommand,
    sendAudioStream,
  };

  return (
    <WebSocketContext.Provider value={contextValue}>
      {children}
    </WebSocketContext.Provider>
  );
}

// Hook to use WebSocket context
export function useWebSocket() {
  const context = useContext(WebSocketContext);
  if (context === undefined) {
    throw new Error("useWebSocket must be used within a WebSocketProvider");
  }
  return context;
}