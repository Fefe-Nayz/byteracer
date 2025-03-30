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
    requestBatteryLevel 
  } = useWebSocket();

  // Request battery level periodically
  useEffect(() => {
    // Initial battery request
    if (status === "connected") {
      requestBatteryLevel();
    }

    // Set up periodic battery level checks
    const interval = setInterval(() => {
      if (status === "connected") {
        requestBatteryLevel();
      }
    }, 30000); // Check every 30 seconds

    return () => clearInterval(interval);
  }, [status, requestBatteryLevel]);

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
          <div className="flex items-center mt-3 pt-2 border-t border-gray-200">
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
      </div>
    </Card>
  );
}
