"use client";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { useEffect } from "react";
import { Card } from "./ui/card";
import { Button } from "./ui/button";
import { Battery } from "lucide-react";

export default function WebSocketStatus() {
  const { 
    status, 
    pingTime, 
    connect, 
    batteryLevel, 
    requestBatteryLevel,
    pythonStatus,
    requestPythonStatus
  } = useWebSocket();

  // Request battery level and Python connection status periodically
  useEffect(() => {
    // Initial requests
    if (status === "connected") {
      requestBatteryLevel();
      requestPythonStatus();
    }

    // Set up periodic checks
    const interval = setInterval(() => {
      if (status === "connected") {
        requestBatteryLevel();
        requestPythonStatus();
      }
    }, 30000); // Check every 30 seconds

    return () => clearInterval(interval);
  }, [status, requestBatteryLevel, requestPythonStatus]);

  // Get battery color based on level
  const getBatteryColor = () => {
    if (!batteryLevel) return "bg-gray-300";
    if (batteryLevel > 50) return "bg-green-500";
    if (batteryLevel > 20) return "bg-yellow-500";
    return "bg-red-500";
  };

  return (
    <Card className="p-4">
      <div>
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-bold">Server Connection</h3>
          <div className="flex items-center">
            <div className="relative flex items-center mr-2">
              <span
              className={`absolute inline-flex h-3 w-3 rounded-full opacity-75 animate-ping ${
                status === "connected"
                ? "bg-green-400"
                : status === "connecting"
                ? "bg-yellow-400"
                : "bg-red-400"
              }`}
              ></span>
              <span
              className={`relative inline-flex h-3 w-3 rounded-full ${
                status === "connected"
                ? "bg-green-500"
                : status === "connecting"
                ? "bg-yellow-500"
                : "bg-red-500"
              }`}
              ></span>
            </div>
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
          <p className="text-xs text-gray-500 mb-2">Ping: {pingTime} ms</p>
        )}

        {status !== "connected" && (
          <Button
            onClick={() => connect()}
            size={'sm'}
          >
            Reconnect
          </Button>
        )}

        {batteryLevel !== null && (
          <div className="flex items-center mt-3 pt-2 border-t border-muted">
            <Battery className="h-4 w-4 mr-2" />
            <div className="flex-1 h-4 bg-gray-200 rounded-full overflow-hidden">
              <div 
                className={`h-full ${getBatteryColor()}`} 
                style={{ width: `${batteryLevel}%` }}
              ></div>
            </div>
            <span className="ml-2 text-xs font-medium">{batteryLevel}%</span>
          </div>
        )}

        {pythonStatus !== null && (
          <div className="flex items-center mt-3 pt-2 border-t border-muted">
            <span className="text-sm font-medium">Python Status:</span>
            <span className={`ml-2 text-xs font-medium ${status === "connected" && pythonStatus === "connected" ? "text-green-500" : "text-red-500"}`}>
              {status === "connected" && pythonStatus === "connected" ? "Connected" : "Disconnected"}
            </span>
          </div>
        )}
      </div>
    </Card>
  );
}
