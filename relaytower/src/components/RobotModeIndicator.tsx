"use client";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { Card } from "./ui/card";
import { 
  Gamepad2, 
  PersonStanding, 
  AlertTriangle, 
  Bot, 
  TrafficCone,
  BarChart, 
  Loader2, 
  Wifi
} from "lucide-react";
import { useState, useEffect, JSX } from "react";

export default function RobotModeIndicator() {
  const { sensorData, status } = useWebSocket();
  const [mode, setMode] = useState<{
    name: string;
    icon: JSX.Element;
    color: string;
  }>({
    name: "Disconnected",
    icon: <Wifi className="h-5 w-5" />,
    color: "text-gray-400"
  });

  useEffect(() => {
    if (status !== "connected") {
      setMode({
        name: "Disconnected",
        icon: <Wifi className="h-5 w-5" />,
        color: "text-gray-400"
      });
      return;
    }

    if (!sensorData) {
      setMode({
        name: "Connecting",
        icon: <Loader2 className="h-5 w-5 animate-spin" />,
        color: "text-yellow-500"
      });
      return;
    }

    // Determine the current mode based on sensor data
    if (sensorData.emergencyState) {
      setMode({
        name: "Emergency",
        icon: <AlertTriangle className="h-5 w-5" />,
        color: "text-red-500"
      });
    } else if (sensorData.isTrackingActive) {
      setMode({
        name: "Tracking",
        icon: <PersonStanding className="h-5 w-5" />,
        color: "text-blue-500"
      });
    } else if (sensorData.isCircuitModeActive) {
      setMode({
        name: "Circuit",
        icon: <TrafficCone className="h-5 w-5" />,
        color: "text-orange-500"
      });
    } else if (sensorData.isDemoModeActive) {
      setMode({
        name: "Demo",
        icon: <BarChart className="h-5 w-5" />,
        color: "text-purple-500"
      });
    } else if (sensorData.isGptModeActive) {
      setMode({
        name: "AI Control",
        icon: <Bot className="h-5 w-5" />,
        color: "text-green-500"
      });
    } else if (sensorData.clientConnected) {
      setMode({
        name: "Manual",
        icon: <Gamepad2 className="h-5 w-5" />,
        color: "text-blue-500"
      });
    } else {
        setMode({
            name: "Waiting for Input",
            icon: <Loader2 className="h-5 w-5 animate-spin" />,
            color: "text-yellow-500"
        });
        }
  }, [sensorData, status]);

  return (
    <Card className="p-2 flex items-center gap-2">
      <div className={`${mode.color}`}>
        {mode.icon}
      </div>
      <span className="font-medium text-sm">{mode.name}</span>
    </Card>
  );
}