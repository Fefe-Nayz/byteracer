"use client";
import { useWebSocket, RobotCommand } from "@/contexts/WebSocketContext";
import { useState, useEffect } from "react";
import { Card } from "./ui/card";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { 
  RefreshCw, Power, Megaphone, Play, MessageSquare,
  RotateCw, Radio, WifiOff, Download, Camera
} from "lucide-react";

interface ActionStatusState {
  command: string;
  status: "idle" | "loading" | "success" | "error";
  message?: string;
}

interface RobotControlsProps {
  showAllControls?: boolean;
}

export default function RobotControls({ showAllControls = false }: RobotControlsProps) {
  const { status, sendRobotCommand, speakText, playSound, restartCameraFeed, sendGptCommand } = useWebSocket();
  const [textToSpeak, setTextToSpeak] = useState("");
  const [gptPrompt, setGptPrompt] = useState("");
  const [selectedSound, setSelectedSound] = useState("klaxon");
  const [actionStatus, setActionStatus] = useState<ActionStatusState>({
    command: "",
    status: "idle"
  });
  const [useCameraForGpt, setUseCameraForGpt] = useState(true);
  
  // Available sounds
  const availableSounds = [
    { id: "klaxon", name: "Klaxon" },
    { id: "fart", name: "Fart" },
    { id: "car_start", name: "Car Start" },
    { id: "car_stop", name: "Car Stop" },
    { id: "beep", name: "Beep" },
    { id: "siren", name: "Siren" },
    { id: "drift", name: "Drift" },
    { id: "accelerate", name: "Accelerate" }
  ];

  // Handle command responses
  useEffect(() => {
    const handleCommandResponse = (e: CustomEvent) => {
      const { success, message, command } = e.detail;
      
      setActionStatus({
        command,
        status: success ? "success" : "error",
        message
      });
      
      // Reset status after a delay
      setTimeout(() => {
        setActionStatus({
          command: "",
          status: "idle"
        });
      }, 3000);
    };
    
    window.addEventListener("debug:command-response", 
      handleCommandResponse as EventListener);
      
    return () => {
      window.removeEventListener("debug:command-response", 
        handleCommandResponse as EventListener);
    };
  }, []);
  
  // Function to execute robot commands
  const executeCommand = (command: RobotCommand) => {
    if (status !== "connected") return;
    
    setActionStatus({
      command,
      status: "loading"
    });
    
    sendRobotCommand(command);
  };
  
  // Handle TTS submission
  const handleTtsSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!textToSpeak.trim() || status !== "connected") return;
    
    speakText(textToSpeak);
    setTextToSpeak("");
  };
  
  // Handle GPT command submission
  const handleGptSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!gptPrompt.trim() || status !== "connected") return;
    
    sendGptCommand(gptPrompt, useCameraForGpt);
    setGptPrompt("");
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
        <h3 className="font-bold mb-3">Quick Controls</h3>
        
        {/* TTS input */}
        <form onSubmit={handleTtsSubmit} className="mb-4">
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
        </form>
        
        {/* Sound player */}
        <div className="flex space-x-2 mb-4">
          <Select 
            value={selectedSound} 
            onValueChange={setSelectedSound}
            disabled={status !== "connected"}
          >
            <SelectTrigger className="flex-grow">
              <SelectValue placeholder="Select a sound" />
            </SelectTrigger>
            <SelectContent>
              {availableSounds.map(sound => (
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
              disabled={status !== "connected" || actionStatus.status === "loading"}
              className="justify-start"
            >
              <RefreshCw className={`h-4 w-4 mr-2 ${
                actionStatus.command === "restart_robot" && actionStatus.status === "loading" ? "animate-spin" : ""
              }`} />
              Restart Robot
              {actionStatus.command === "restart_robot" && renderActionState()}
            </Button>
            
            <Button 
              variant="outline" 
              size="sm"
              onClick={() => executeCommand("stop_robot")}
              disabled={status !== "connected" || actionStatus.status === "loading"}
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
              disabled={status !== "connected" || actionStatus.status === "loading"}
              className="justify-start"
            >
              <RotateCw className={`h-4 w-4 mr-2 ${
                actionStatus.command === "restart_all_services" && actionStatus.status === "loading" ? "animate-spin" : ""
              }`} />
              Restart All Services
              {actionStatus.command === "restart_all_services" && renderActionState()}
            </Button>
            
            <Button 
              variant="outline" 
              size="sm"
              onClick={() => executeCommand("check_for_updates")}
              disabled={status !== "connected" || actionStatus.status === "loading"}
              className="justify-start"
            >
              <Download className="h-4 w-4 mr-2" />
              Check for Updates
              {actionStatus.command === "check_for_updates" && renderActionState()}
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
              disabled={status !== "connected" || actionStatus.status === "loading"}
              className="justify-start"
            >
              <RotateCw className={`h-4 w-4 mr-2 ${
                actionStatus.command === "restart_python_service" && actionStatus.status === "loading" ? "animate-spin" : ""
              }`} />
              Restart Python Service
              {actionStatus.command === "restart_python_service" && renderActionState()}
            </Button>
            
            <Button 
              variant="outline" 
              size="sm"
              onClick={() => executeCommand("restart_websocket")}
              disabled={status !== "connected" || actionStatus.status === "loading"}
              className="justify-start"
            >
              <Radio className="h-4 w-4 mr-2" />
              Restart WebSocket
              {actionStatus.command === "restart_websocket" && renderActionState()}
            </Button>
            
            <Button 
              variant="outline" 
              size="sm"
              onClick={() => executeCommand("restart_web_server")}
              disabled={status !== "connected" || actionStatus.status === "loading"}
              className="justify-start"
            >
              <WifiOff className="h-4 w-4 mr-2" />
              Restart Web Server
              {actionStatus.command === "restart_web_server" && renderActionState()}
            </Button>
            
            <Button 
              variant="outline" 
              size="sm"
              onClick={() => restartCameraFeed()}
              disabled={status !== "connected" || actionStatus.status === "loading"}
              className="justify-start"
            >
              <Camera className="h-4 w-4 mr-2" />
              Restart Camera Feed
              {actionStatus.command === "restart_camera_feed" && renderActionState()}
            </Button>
          </div>
        </div>
      </div>
      
      {/* Text-to-Speech section */}
      <div className="border-t pt-4 pb-2">
        <h4 className="text-sm font-semibold mb-2">Text-to-Speech</h4>
        <form onSubmit={handleTtsSubmit}>
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
        </form>
      </div>
      
      {/* Sound player section */}
      <div className="border-t pt-4 pb-2">
        <h4 className="text-sm font-semibold mb-2">Play Sound</h4>
        <div className="flex space-x-2">
          <Select 
            value={selectedSound} 
            onValueChange={setSelectedSound}
            disabled={status !== "connected"}
          >
            <SelectTrigger className="flex-grow">
              <SelectValue placeholder="Select a sound" />
            </SelectTrigger>
            <SelectContent>
              {availableSounds.map(sound => (
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
      </div>
      
      {/* GPT Commands section */}
      <div className="border-t pt-4">
        <h4 className="text-sm font-semibold mb-2">GPT Commands</h4>
        <form onSubmit={handleGptSubmit}>
          <div className="mb-2">
            <Input
              placeholder="Ask GPT to control the robot..."
              value={gptPrompt}
              onChange={(e) => setGptPrompt(e.target.value)}
              disabled={status !== "connected"}
            />
          </div>
          <div className="flex justify-between items-center">
            <div className="flex items-center">
              <input
                type="checkbox"
                id="use-camera"
                checked={useCameraForGpt}
                onChange={() => setUseCameraForGpt(!useCameraForGpt)}
                className="mr-2"
              />
              <label htmlFor="use-camera" className="text-xs">Use camera feed</label>
            </div>
            <Button 
              type="submit" 
              size="sm"
              disabled={status !== "connected" || !gptPrompt.trim()}
            >
              <MessageSquare className="h-4 w-4 mr-1" />
              Send
            </Button>
          </div>
        </form>
      </div>
    </Card>
  );
  
  // Helper function to render action status
  function renderActionState() {
    switch (actionStatus.status) {
      case "loading":
        return <span className="ml-auto text-xs bg-yellow-100 text-yellow-800 px-2 py-0.5 rounded">Loading...</span>;
      case "success":
        return <span className="ml-auto text-xs bg-green-100 text-green-800 px-2 py-0.5 rounded">Success</span>;
      case "error":
        return <span className="ml-auto text-xs bg-red-100 text-red-800 px-2 py-0.5 rounded">Error</span>;
      default:
        return null;
    }
  }
}