"use client";
import { useState, useEffect } from "react";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { Progress } from "./ui/progress";
import { 
  AlertOctagon,
  Battery,
  BatteryWarning,
  BatteryCharging,
  ChevronUp,
  ChevronDown,
  Car,
  MoveHorizontal
} from "lucide-react";

// ShieldAlert,
// Gauge,
// Eye,

export default function MiniSensorOverlay({ position = "bottom-right" }: { position?: string }) {
  const { sensorData, status } = useWebSocket();
  const [expanded, setExpanded] = useState<boolean>(false);
  const [emergencyAlert, setEmergencyAlert] = useState<boolean>(false);
  
  // Flash emergency alert when emergency state changes
  useEffect(() => {
    if (sensorData?.emergencyState) {
      setEmergencyAlert(true);
      const timer = setTimeout(() => {
        setEmergencyAlert(false);
      }, 5000);
      return () => clearTimeout(timer);
    } else {
      setEmergencyAlert(false);
    }
  }, [sensorData?.emergencyState]);

  // If no connection or no data, don't show anything
  if (status !== "connected" || !sensorData) {
    return null;
  }

  // Get battery icon based on level
  const getBatteryIcon = (level: number) => {
    if (level <= 20) return <BatteryWarning className="h-4 w-4 text-red-500" />;
    if (level <= 40) return <Battery className="h-4 w-4 text-yellow-500" />;
    return <BatteryCharging className="h-4 w-4 text-green-500" />;
  };
  
  // Get battery color class
  const getBatteryColorClass = (level: number) => {
    if (level <= 20) return "text-red-500";
    if (level <= 40) return "text-yellow-500";
    return "text-green-500";
  };
  
  // Determine color for ultrasonic distance
  const getDistanceColor = (distance: number) => {
    if (distance > 50) return "text-green-500";
    if (distance > 20) return "text-yellow-500";
    return "text-red-500";
  };
  
  // Check if safety system is active
//   const isSafetyActive = sensorData.isCollisionAvoidanceActive || sensorData.isEdgeDetectionActive;

  // Define position classes based on position prop
  const positionClasses = {
    "top-left": "top-6 left-6",
    "top-right": "top-6 right-6",
    "bottom-left": "bottom-6 left-6",
    "bottom-right": "bottom-6 right-6"
  }[position] || "bottom-6 right-6";

  // Format emergency state message
  const formatEmergencyMessage = (state: string | null) => {
    if (!state) return "";
    return state.toLowerCase()
      .replace(/_/g, ' ')
      .replace(/\b\w/g, char => char.toUpperCase());
  };

  return (
    <div 
      className={`absolute ${positionClasses} z-40 bg-black/50 backdrop-blur-sm rounded-md shadow-lg transition-all duration-200 overflow-hidden`}
      style={{ maxWidth: expanded ? "280px" : "180px" }}
    >
      {/* Header with battery and toggle */}
      <div className="p-2 flex items-center justify-between cursor-pointer" onClick={() => setExpanded(!expanded)}>
        <div className="flex items-center space-x-1">
          {emergencyAlert ? (
            <div className="flex items-center space-x-1 animate-pulse">
              <AlertOctagon className="h-4 w-4 text-red-500" />
              <span className="text-xs font-medium text-red-500">
                {formatEmergencyMessage(sensorData.emergencyState)}
              </span>
            </div>
          ) : (
            <>
              {getBatteryIcon(sensorData.batteryLevel)}
              <span className={`text-xs font-medium ${getBatteryColorClass(sensorData.batteryLevel)}`}>
                {sensorData.batteryLevel}%
              </span>
            </>
          )}
        </div>
        
        {/* Toggle icon */}
        <div className="flex items-center text-white">
          {expanded ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronUp className="h-4 w-4" />
          )}
        </div>
      </div>
      
      {/* Expanded content */}
      {expanded && (
        <div className="px-2 pb-2 text-white space-y-2">
          {/* Motion data */}
          <div className="space-y-1">
            <div className="flex items-center mb-1">
              <Car className="h-3 w-3 mr-1" />
              <span className="text-xs">Motion</span>
            </div>
            
            <div className="grid grid-cols-3 gap-1 text-[10px]">
              <div>
                <div className="flex justify-between">
                  <span>Speed</span>
                  <span 
                    className={Math.abs(sensorData.speed || 0) > 0.1 ? 'text-blue-300' : 'text-gray-400'}
                  >
                    {((sensorData.speed || 0) * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="relative w-full h-1 bg-gray-800 rounded-full overflow-hidden">
                  <div 
                    className={`absolute left-0 top-0 bottom-0 ${(sensorData.speed || 0) > 0 ? 'bg-blue-500' : 'bg-orange-500'}`}
                    style={{ 
                      width: `${Math.min(100, Math.abs((sensorData.speed || 0) * 100))}%`,
                      left: (sensorData.speed || 0) < 0 ? 'auto' : '0',
                      right: (sensorData.speed || 0) < 0 ? '0' : 'auto'
                    }}
                  ></div>
                </div>
              </div>
              
              <div>
                <div className="flex justify-between">
                  <span>Turn</span>
                  <span 
                    className={Math.abs(sensorData.turn || 0) > 0.1 ? 'text-green-300' : 'text-gray-400'}
                  >
                    {((sensorData.turn || 0) * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="relative w-full h-1 bg-gray-800 rounded-full overflow-hidden">
                  <div 
                    className={`absolute left-0 top-0 bottom-0 ${(sensorData.turn || 0) > 0 ? 'bg-green-500' : 'bg-purple-500'}`}
                    style={{ 
                      width: `${Math.min(100, Math.abs((sensorData.turn || 0) * 100))}%`,
                      left: (sensorData.turn || 0) < 0 ? 'auto' : '0',
                      right: (sensorData.turn || 0) < 0 ? '0' : 'auto'
                    }}
                  ></div>
                </div>
              </div>
              
              <div>
                <div className="flex justify-between">
                  <span>Accel</span>
                  <span 
                    className={Math.abs(sensorData.acceleration || 0) > 0.5 ? 'text-amber-300' : 'text-gray-400'}
                  >
                    {((sensorData.acceleration || 0) * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="relative w-full h-1 bg-gray-800 rounded-full overflow-hidden">
                  <div 
                    className="absolute top-0 bottom-0 bg-amber-500"
                    style={{ 
                      width: `${Math.min(100, Math.abs((sensorData.acceleration || 0) * 50))}%`,
                      left: '50%',
                      transform: `translateX(${(sensorData.acceleration || 0) >= 0 ? '0' : '-100%'})`,
                    }}
                  ></div>
                </div>
              </div>
            </div>
          </div>
          
          {/* Distance sensor */}
          <div className="space-y-1">
            <div className="flex items-center justify-between text-[10px]">
              <div className="flex items-center">
                <MoveHorizontal className="h-3 w-3 mr-1" />
                <span>Distance</span>
              </div>
              <span className={getDistanceColor(sensorData.ultrasonicDistance)}>
                {sensorData.ultrasonicDistance} cm
              </span>
            </div>
            <div className="relative w-full h-1 bg-gray-800 rounded-full overflow-hidden">
              <div 
                className={`absolute left-0 top-0 bottom-0 ${getDistanceColor(sensorData.ultrasonicDistance).replace('text-', 'bg-')}`}
                style={{ width: `${Math.min(100, Math.max(0, (sensorData.ultrasonicDistance / 100) * 100))}%` }}
              ></div>
            </div>
          </div>
          
          {/* Safety systems */}
          <div className="text-[10px] flex flex-wrap gap-1">
            <div className={`flex items-center px-1.5 py-0.5 rounded-sm ${sensorData.isCollisionAvoidanceActive ? 'bg-green-900/50 text-green-300' : 'bg-gray-800/80 text-gray-400'}`}>
              <div className={`w-1.5 h-1.5 rounded-full mr-1 ${sensorData.isCollisionAvoidanceActive ? 'bg-green-500' : 'bg-gray-600'}`}></div>
              <span>Collision</span>
            </div>
            <div className={`flex items-center px-1.5 py-0.5 rounded-sm ${sensorData.isEdgeDetectionActive ? 'bg-green-900/50 text-green-300' : 'bg-gray-800/80 text-gray-400'}`}>
              <div className={`w-1.5 h-1.5 rounded-full mr-1 ${sensorData.isEdgeDetectionActive ? 'bg-green-500' : 'bg-gray-600'}`}></div>
              <span>Edge</span>
            </div>
            <div className={`flex items-center px-1.5 py-0.5 rounded-sm ${sensorData.isAutoStopActive ? 'bg-green-900/50 text-green-300' : 'bg-gray-800/80 text-gray-400'}`}>
              <div className={`w-1.5 h-1.5 rounded-full mr-1 ${sensorData.isAutoStopActive ? 'bg-green-500' : 'bg-gray-600'}`}></div>
              <span>Auto Stop</span>
            </div>
            {(sensorData.isTrackingActive || sensorData.isCircuitModeActive) && (
              <div className={`flex items-center px-1.5 py-0.5 rounded-sm ${sensorData.isTrackingActive ? 'bg-blue-900/50 text-blue-300' : 'bg-gray-800/80 text-gray-400'}`}>
                <div className={`w-1.5 h-1.5 rounded-full mr-1 ${sensorData.isTrackingActive ? 'bg-blue-500' : 'bg-gray-600'}`}></div>
                <span>{sensorData.isTrackingActive ? 'Tracking' : 'Circuit'}</span>
              </div>
            )}
          </div>
          
          {/* Bottom row with CPU/RAM stats */}
          <div className="grid grid-cols-2 gap-2 text-[10px]">
            <div>
              <div className="flex justify-between">
                <span>CPU</span>
                <span className={sensorData.cpuUsage > 80 ? 'text-red-400' : sensorData.cpuUsage > 60 ? 'text-yellow-400' : 'text-green-400'}>
                  {(sensorData.cpuUsage || 0).toFixed(0)}%
                </span>
              </div>
              <Progress 
                value={sensorData.cpuUsage || 0} 
                className="h-1 bg-gray-800"
              />
            </div>
            <div>
              <div className="flex justify-between">
                <span>RAM</span>
                <span className={sensorData.ramUsage > 80 ? 'text-red-400' : sensorData.ramUsage > 60 ? 'text-yellow-400' : 'text-green-400'}>
                  {(sensorData.ramUsage || 0).toFixed(0)}%
                </span>
              </div>
              <Progress 
                value={sensorData.ramUsage || 0} 
                className="h-1 bg-gray-800"
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}