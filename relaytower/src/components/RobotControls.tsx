"use client";
import { useWebSocket, RobotCommand } from "@/contexts/WebSocketContext";
import { useState, useEffect } from "react";
import { Card } from "./ui/card";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./ui/select";
import {
  RefreshCw,
  Power,
  Megaphone,
  Play,
  RotateCw,
  Radio,
  WifiOff,
  Download,
  Camera,
  PersonStanding,
  TrafficCone,
  BarChart,
  Gamepad2,
} from "lucide-react";

interface ActionStatusState {
  command: string;
  status: "idle" | "loading" | "success" | "error";
  message?: string;
}

interface RobotControlsProps {
  showAllControls?: boolean;
}

export default function RobotControls({
  showAllControls = false,
}: RobotControlsProps) {
  const {
    status,
    sendRobotCommand,
    speakText,
    playSound,
    restartCameraFeed,
    settings,
    requestSettings,
    updateSettings,
  } = useWebSocket();
  const [textToSpeak, setTextToSpeak] = useState("");
  const [language, setLanguage] = useState("");
  const [selectedSound, setSelectedSound] = useState("klaxon");
  const [actionStatus, setActionStatus] = useState<ActionStatusState>({
    command: "",
    status: "idle",
  });

  useEffect(() => {
    requestSettings();
  }, [requestSettings]);

  // Languages available for TTS
  const languages = [
    { value: "en-US", label: "English (US)" },
    { value: "en-GB", label: "English (UK)" },
    { value: "fr-FR", label: "French" },
    { value: "de-DE", label: "German" },
    { value: "es-ES", label: "Spanish" },
    { value: "it-IT", label: "Italian" },
  ];

  // Set default language from settings when component loads or settings change
  useEffect(() => {
    if (settings?.sound.tts_language) {
      setLanguage(settings.sound.tts_language);
    }
  }, [settings]);

  // Available sounds

  const availableSounds = [
    { id: "fart", name: "💨 Fart" },
    { id: "klaxon", name: "📢 Klaxon" },
    { id: "alarm", name: "🚨 Alarm" },
    { id: "wow", name: "🤩 Wow" },
    { id: "laugh", name: "😂 Laugh" },
    { id: "bruh", name: "😑 Bruh" },
    { id: "nope", name: "❌ Nope" },
    { id: "lingango", name: "🗣️ Lingango" },
    // { id: "cailloux", name: "🪨 Cailloux"},
    // { id: "fave", name: "🎤 Favéé"},
    { id: "pipe", name: "🔩 Pipe" },
    // { id: "tuile", name: "🧱 Une Tuile"},
    // { id: "india", name: "🇮🇳 India"},
    { id: "vine-boom", name: "💥 Vine Boom" },
    { id: "tralalelo-tralala", name: "🦈 Tralalelo" },
    { id: "get-out", name: "🚪 Get Out" },
    // { id:"scream", name: "😱 Scream"},
    // { id:"wtf", name: "🤯 WTF"},
    { id: "rat-dance", name: "🐀 Rat Dance" },
    // { id:"ph", name: "🤨 PH"},
    // { id:"aurores", name: "🐉 Dragorores"},
  ];

  // Handle command responses
  useEffect(() => {
    const handleCommandResponse = (e: CustomEvent) => {
      const { success, message, command } = e.detail;

      setActionStatus({
        command,
        status: success ? "success" : "error",
        message,
      });

      // Reset status after a delay
      setTimeout(() => {
        setActionStatus({
          command: "",
          status: "idle",
        });
      }, 3000);
    };

    window.addEventListener(
      "debug:command-response",
      handleCommandResponse as EventListener
    );

    return () => {
      window.removeEventListener(
        "debug:command-response",
        handleCommandResponse as EventListener
      );
    };
  }, []);

  // Function to execute robot commands
  const executeCommand = (command: RobotCommand) => {
    if (status !== "connected") return;

    setActionStatus({
      command,
      status: "loading",
    });

    sendRobotCommand(command);
  };

  // Handle TTS submission
  const handleTtsSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!textToSpeak.trim() || status !== "connected") return;

    speakText(textToSpeak, language);
    setTextToSpeak("");
  };

  // Handle sound playback
  const handlePlaySound = () => {
    if (status !== "connected") return;
    playSound(selectedSound);
  };

  // Basic controls for main panel
  if (!showAllControls) {
    return (
      <Card className="p-4">
        <h3 className="font-bold">Quick Controls</h3>

        {/* TTS input */}
        <form onSubmit={handleTtsSubmit} className="space-y-2">
          <div className="flex space-x-2">
            <Input
              placeholder="Text to speak..."
              value={textToSpeak}
              onChange={(e) => setTextToSpeak(e.target.value)}
              disabled={status !== "connected"}
            />
            <Button
              type="submit"
              size="sm"
              disabled={status !== "connected" || !textToSpeak.trim()}
            >
              <Megaphone className="h-4 w-4" />
            </Button>
          </div>
          <Select
            value={language}
            onValueChange={(value) => setLanguage(value)}
            disabled={status !== "connected"}
          >
            <SelectTrigger className="w-full">
              <SelectValue placeholder="Select language" />
            </SelectTrigger>
            <SelectContent>
              {languages.map((lang) => (
                <SelectItem key={lang.value} value={lang.value}>
                  {lang.label}
                  {lang.value === settings?.sound.tts_language && " (Default)"}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </form>

        {/* Sound player */}
        <div className="flex space-x-2 mb-1">
          <Select
            value={selectedSound}
            onValueChange={setSelectedSound}
            disabled={status !== "connected"}
          >
            <SelectTrigger className="flex-grow">
              <SelectValue placeholder="Select a sound" />
            </SelectTrigger>
            <SelectContent>
              {availableSounds.map((sound) => (
                <SelectItem key={sound.id} value={sound.id}>
                  {sound.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            size="sm"
            onClick={handlePlaySound}
            disabled={status !== "connected"}
          >
            <Play className="h-4 w-4" />
          </Button>
        </div>

        {/* Mode Selector */}
        <div>
          <Select
            value={
              settings?.modes.normal_mode_enabled
                ? "normal"
                : settings?.modes.tracking_enabled
                ? "tracking"
                : settings?.modes.circuit_mode_enabled
                ? "circuit"
                : settings?.modes.demo_mode_enabled
                ? "demo"
                : "normal" // Default fallback
            }
            onValueChange={(value) => {
              if (settings) {
                // Create updated settings with the selected mode enabled and others disabled
                const updatedSettings = {
                  ...settings,
                  modes: {
                    ...settings.modes,
                    normal_mode_enabled: value === "normal",
                    tracking_enabled: value === "tracking",
                    circuit_mode_enabled: value === "circuit",
                    demo_mode_enabled: value === "demo",
                  },
                };
                updateSettings(updatedSettings);
              }
            }}
            disabled={status !== "connected" || !settings}
          >
            <SelectTrigger className="w-full">
              <SelectValue placeholder="Select mode" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="normal">
                <div className="flex items-center space-x-2">
                  <Gamepad2 className="h-4 w-4" />
                  <span>Default Controller Mode</span>
                </div>
              </SelectItem>
              <SelectItem value="tracking">
                <div className="flex items-center space-x-2">
                  <PersonStanding className="h-4 w-4" />
                  <span>Person Tracking</span>
                </div>
              </SelectItem>
              <SelectItem value="circuit">
                <div className="flex items-center space-x-2">
                  <TrafficCone className="h-4 w-4" />
                  <span>Circuit Mode</span>
                </div>
              </SelectItem>
              <SelectItem value="demo">
                <div className="flex items-center space-x-2">
                  <BarChart className="h-4 w-4" />
                  <span>Demo Mode</span>
                </div>
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Essential controls */}
        <div className="grid grid-cols-2 gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => executeCommand("restart_camera_feed")}
            disabled={status !== "connected"}
          >
            <Camera className="h-4 w-4 mr-1" />
            Restart Camera
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={() => executeCommand("emergency_stop")}
            disabled={status !== "connected"}
          >
            <Power className="h-4 w-4 mr-1" />
            Emergency Stop
          </Button>
        </div>
      </Card>
    );
  }

  // Full controls for system panel
  return (
    <Card className="p-4">
      <h3 className="font-bold mb-3">Robot Controls</h3>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        {/* System controls */}
        <div className="space-y-3">
          <h4 className="text-sm font-semibold">System</h4>

          <div className="grid grid-cols-1 gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => executeCommand("restart_robot")}
              disabled={
                status !== "connected" || actionStatus.status === "loading"
              }
              className="justify-start"
            >
              <RefreshCw
                className={`h-4 w-4 mr-2 ${
                  actionStatus.command === "restart_robot" &&
                  actionStatus.status === "loading"
                    ? "animate-spin"
                    : ""
                }`}
              />
              Restart Robot
              {actionStatus.command === "restart_robot" && renderActionState()}
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={() => executeCommand("stop_robot")}
              disabled={
                status !== "connected" || actionStatus.status === "loading"
              }
              className="justify-start"
            >
              <Power className="h-4 w-4 mr-2" />
              Shut Down Robot
              {actionStatus.command === "stop_robot" && renderActionState()}
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={() => executeCommand("restart_all_services")}
              disabled={
                status !== "connected" || actionStatus.status === "loading"
              }
              className="justify-start"
            >
              <RotateCw
                className={`h-4 w-4 mr-2 ${
                  actionStatus.command === "restart_all_services" &&
                  actionStatus.status === "loading"
                    ? "animate-spin"
                    : ""
                }`}
              />
              Restart All Services
              {actionStatus.command === "restart_all_services" &&
                renderActionState()}
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={() => executeCommand("check_for_updates")}
              disabled={
                status !== "connected" || actionStatus.status === "loading"
              }
              className="justify-start"
            >
              <Download className="h-4 w-4 mr-2" />
              Check for Updates
              {actionStatus.command === "check_for_updates" &&
                renderActionState()}
            </Button>
          </div>
        </div>

        {/* Service controls */}
        <div className="space-y-3">
          <h4 className="text-sm font-semibold">Services</h4>

          <div className="grid grid-cols-1 gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => executeCommand("restart_python_service")}
              disabled={
                status !== "connected" || actionStatus.status === "loading"
              }
              className="justify-start"
            >
              <RotateCw
                className={`h-4 w-4 mr-2 ${
                  actionStatus.command === "restart_python_service" &&
                  actionStatus.status === "loading"
                    ? "animate-spin"
                    : ""
                }`}
              />
              Restart Python Service
              {actionStatus.command === "restart_python_service" &&
                renderActionState()}
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={() => executeCommand("restart_websocket")}
              disabled={
                status !== "connected" || actionStatus.status === "loading"
              }
              className="justify-start"
            >
              <Radio className="h-4 w-4 mr-2" />
              Restart WebSocket
              {actionStatus.command === "restart_websocket" &&
                renderActionState()}
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={() => executeCommand("restart_web_server")}
              disabled={
                status !== "connected" || actionStatus.status === "loading"
              }
              className="justify-start"
            >
              <WifiOff className="h-4 w-4 mr-2" />
              Restart Web Server
              {actionStatus.command === "restart_web_server" &&
                renderActionState()}
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={() => restartCameraFeed()}
              disabled={
                status !== "connected" || actionStatus.status === "loading"
              }
              className="justify-start"
            >
              <Camera className="h-4 w-4 mr-2" />
              Restart Camera Feed
              {actionStatus.command === "restart_camera_feed" &&
                renderActionState()}
            </Button>
          </div>
        </div>
      </div>
    </Card>
  );

  // Helper function to render action status
  function renderActionState() {
    switch (actionStatus.status) {
      case "loading":
        return (
          <span className="ml-auto text-xs bg-yellow-100 text-yellow-800 px-2 py-0.5 rounded">
            Loading...
          </span>
        );
      case "success":
        return (
          <span className="ml-auto text-xs bg-green-100 text-green-800 px-2 py-0.5 rounded">
            Success
          </span>
        );
      case "error":
        return (
          <span className="ml-auto text-xs bg-red-100 text-red-800 px-2 py-0.5 rounded">
            Error
          </span>
        );
      default:
        return null;
    }
  }
}
