"use client";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { useEffect, useState } from "react";
import { Card } from "./ui/card";
import { Progress } from "./ui/progress";
import { 
  RadioTower, 
  MoveHorizontal, 
  Car, 
  AlertOctagon,
  Battery,
  BatteryWarning,
  BatteryCharging,
  ShieldAlert,
  Cpu,
  MemoryStick
} from "lucide-react";

export default function SensorData() {
  const { sensorData, status, settings } = useWebSocket();
  const [emergencyAlert, setEmergencyAlert] = useState<boolean>(false);
  
  // These states track the last non-zero sign of speed and turn
  // so that if the value snaps to zero, the bar remains anchored
  // on the correct side for the shrink animation.
  const [prevSpeedSign, setPrevSpeedSign] = useState(0);
  const [prevTurnSign, setPrevTurnSign] = useState(0);

  // Update prevSpeedSign whenever speed changes sign
  useEffect(() => {
    const s = sensorData?.speed || 0;
    if (s > 0) setPrevSpeedSign(1);
    else if (s < 0) setPrevSpeedSign(-1);
    // if s === 0, keep the last sign as is
  }, [sensorData?.speed]);

  // Update prevTurnSign whenever turn changes sign
  useEffect(() => {
    const t = sensorData?.turn || 0;
    if (t > 0) setPrevTurnSign(1);
    else if (t < 0) setPrevTurnSign(-1);
    // if t === 0, keep the last sign as is
  }, [sensorData?.turn]);

  // Helper to compute the correct left/right anchoring for speed
  const getSpeedAnchor = () => {
    const s = sensorData?.speed || 0;
    if (s < 0) {
      return { left: "auto", right: 0 };
    } else if (s > 0) {
      return { left: 0, right: "auto" };
    } else {
      // If speed is zero, anchor according to last known sign
      return prevSpeedSign < 0
        ? { left: "auto", right: 0 }
        : { left: 0, right: "auto" };
    }
  };

  // Helper to compute the correct left/right anchoring for turn
  const getTurnAnchor = () => {
    const t = sensorData?.turn || 0;
    if (t < 0) {
      return { left: "auto", right: 0 };
    } else if (t > 0) {
      return { left: 0, right: "auto" };
    } else {
      // If turn is zero, anchor according to last known sign
      return prevTurnSign < 0
        ? { left: "auto", right: 0 }
        : { left: 0, right: "auto" };
    }
  };

  // Flash emergency alert when emergency state changes
  useEffect(() => {
    if (sensorData?.emergencyState) {
      setEmergencyAlert(true);
      
      // Add audio feedback for emergencies
      if (typeof window !== 'undefined') {
        try {
          const audio = new Audio('/alert.mp3');
          audio.volume = 0.3;
          audio.play().catch(() => {});
        } catch (_) {
          console.error("Failed to play alert sound:", _);
        }
      }
      
      const timer = setTimeout(() => {
        setEmergencyAlert(false);
      }, 5000);
      return () => clearTimeout(timer);
    } else {
      // Reset emergency alert if emergency state is cleared
      setEmergencyAlert(false);
    }
  }, [sensorData?.emergencyState]);

  // If no connection or no data, show placeholder
  if (status !== "connected" || !sensorData) {
    return (
      <Card className="p-4">
        <h3 className="font-bold mb-3">Sensor Data</h3>
        <div className="text-sm text-gray-500 italic">
          {status === "connected" 
            ? "Waiting for sensor data..." 
            : "Connect to robot to view sensor data"}
        </div>
      </Card>
    );
  }

  // Get thresholds from settings or use defaults
  const lineBlackThreshold = (settings?.safety?.edge_threshold  || 200 ) * 1000;
  const collisionDangerThreshold = settings?.safety?.collision_threshold || 10;
  const collisionWarningThreshold = (settings?.safety?.collision_threshold || 10 ) + 5;

  // Determine color for ultrasonic distance based on settings
  const getDistanceColor = (distance: number) => {
    if (distance > collisionWarningThreshold) return "text-green-500";
    if (distance > collisionDangerThreshold) return "text-yellow-500";
    return "text-red-500";
  };

  // Format line sensor values
  const formatLineSensor = (value: number) => {
    return Math.round(value * 100) / 100;
  };
  
  // Get battery icon based on level
  const getBatteryIcon = (level: number) => {
    if (level <= 20) return <BatteryWarning className="h-5 w-5 text-red-500" />;
    if (level <= 40) return <Battery className="h-5 w-5 text-yellow-500" />;
    return <BatteryCharging className="h-5 w-5 text-green-500" />;
  };
  
  // Get battery color class
  const getBatteryColorClass = (level: number) => {
    if (level <= 20) return "text-red-500";
    if (level <= 40) return "text-yellow-500";
    return "text-green-500";
  };
  
  // Get progress color for battery
  const getBatteryProgressColor = (level: number) => {
    if (level <= 20) return "bg-red-500";
    if (level <= 40) return "bg-yellow-500";
    return "bg-green-500";
  };
  
  // Get resource usage color
  const getResourceColor = (usage: number) => {
    if (usage >= 80) return "text-red-500";
    if (usage >= 60) return "text-yellow-500";
    return "text-green-500";
  };
  
  // Get resource progress color
  const getResourceProgressColor = (usage: number) => {
    if (usage >= 80) return "bg-red-500";
    if (usage >= 60) return "bg-yellow-500";
    return "bg-green-500";
  };
  
  // Helper to format emergency state message
  const formatEmergencyMessage = (state: string | null) => {
    if (!state) return "";
    
    // Replace underscores with spaces and capitalize
    return state.toLowerCase()
      .replace(/_/g, ' ')
      .replace(/\b\w/g, char => char.toUpperCase());
  };
  
  // Check if safety system is active
  const isSafetyActive = sensorData.isCollisionAvoidanceActive || sensorData.isEdgeDetectionActive;

  return (
    <Card className={`p-4 ${emergencyAlert ? 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800' : 'border bg-card'}`}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-bold">Sensor Data</h3>
        
        {/* Emergency state indicator */}
        {sensorData.emergencyState && (
          <div className={`flex items-center space-x-1 text-red-500 ${emergencyAlert ? 'animate-pulse' : ''}`}>
            <AlertOctagon className="h-5 w-5" />
            <span className="text-sm font-semibold">{formatEmergencyMessage(sensorData.emergencyState)}</span>
          </div>
        )}
      </div>

      {/* Battery level indicator */}
      <div className="mb-4">
        <div className="flex items-center mb-1">
          {getBatteryIcon(sensorData.batteryLevel)}
          <span className="text-sm font-medium ml-2">Battery Level:</span>
          <span className={`ml-auto font-medium ${getBatteryColorClass(sensorData.batteryLevel)}`}>
            {sensorData.batteryLevel}%
          </span>
        </div>
        <Progress 
          value={sensorData.batteryLevel} 
          className={`h-2 ${getBatteryProgressColor(sensorData.batteryLevel)}`}
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
       {/* Motion data - section for speed, turn, and acceleration */}
       <div className="p-3 rounded-md bg-muted">
          <div className="flex items-center mb-2">
            <Car className="h-4 w-4 mr-2" />
            <span className="text-sm font-medium">Motion Data:</span>
          </div>
          <div className="space-y-2">
            {/* Speed */}
            <div className="flex items-center justify-between text-xs">
              <span>Speed:</span>
              <span
                className={`font-medium ${
                  (sensorData.speed || 0) === 0
                    ? 'text-gray-500'
                    : (sensorData.speed || 0) > 0
                      ? 'text-blue-600'
                      : 'text-orange-600'
                }`}
              >
                {((sensorData.speed || 0) * 100).toFixed(0)}%
              </span>
            </div>
            <div className="relative w-full h-2 bg-gray-200 rounded-full overflow-hidden">
              <div 
                className={`absolute top-0 bottom-0 transition-[width] duration-300 ease-out ${
                  (sensorData.speed || 0) > 0 
                    ? 'bg-gradient-to-r from-blue-400 to-blue-600' 
                    : 'bg-gradient-to-r from-orange-400 to-orange-600'
                }`}
                style={{ 
                  width: `${Math.min(100, Math.abs((sensorData.speed || 0) * 100))}%`,
                  ...getSpeedAnchor()
                }}
              >
                <div className="absolute right-0 top-0 bottom-0 w-1 bg-white opacity-70"></div>
              </div>
            </div>
            
            {/* Turn */}
            <div className="flex items-center justify-between text-xs mt-3">
              <span>Turn:</span>
              <span
                className={`font-medium ${
                  (sensorData.turn || 0) === 0
                    ? 'text-gray-500'
                    : (sensorData.turn || 0) > 0
                      ? 'text-emerald-600'
                      : 'text-purple-600'
                }`}
              >
                {((sensorData.turn || 0) * 100).toFixed(0)}%
              </span>
            </div>
            <div className="relative w-full h-2 bg-gray-200 rounded-full overflow-hidden">
              <div 
                className={`absolute top-0 bottom-0 transition-[width] duration-300 ease-out ${
                  (sensorData.turn || 0) > 0 
                    ? 'bg-gradient-to-r from-emerald-400 to-emerald-600' 
                    : 'bg-gradient-to-r from-purple-400 to-purple-600'
                }`}
                style={{ 
                  width: `${Math.min(100, Math.abs((sensorData.turn || 0) * 100))}%`,
                  ...getTurnAnchor()
                }}
              >
                <div className="absolute right-0 top-0 bottom-0 w-1 bg-white opacity-70"></div>
              </div>
            </div>
            
            {/* Acceleration */}
            <div className="flex items-center justify-between text-xs mt-3">
              <span>Acceleration:</span>
              {/* Fix for color matching positive/negative */}
              <span
                className={`font-medium ${
                  (sensorData.acceleration || 0) === 0
                    ? 'text-gray-500'
                    : (sensorData.acceleration || 0) > 0
                      ? 'text-amber-600'
                      : 'text-red-600'
                }`}
              >
                {((sensorData.acceleration || 0) * 100).toFixed(0)}%
              </span>
            </div>
            <div className="relative w-full h-2 bg-gray-200 rounded-full overflow-hidden">
              <div className="absolute top-0 bottom-0 left-1/2 w-px h-full bg-gray-400"></div>
              <div 
                className={`absolute top-0 bottom-0 transition-all duration-300 ease-out ${
                  (sensorData.acceleration || 0) >= 0 
                    ? 'bg-gradient-to-r from-amber-400 to-amber-600' 
                    : 'bg-gradient-to-r from-red-400 to-red-600'
                }`}
                style={{ 
                  width: `${Math.min(50, Math.abs((sensorData.acceleration || 0) * 50))}%`,
                  left: (sensorData.acceleration || 0) >= 0
                    ? '50%'
                    : `calc(50% - ${Math.min(50, Math.abs((sensorData.acceleration || 0) * 50))}%)`,
                }}
              >
                <div className={`absolute ${(sensorData.acceleration || 0) >= 0 ? 'right' : 'left'}-0 top-0 bottom-0 w-1 bg-white opacity-70`}></div>
              </div>
            </div>
          </div>
        </div>
        
        {/* Safety status */}
        <div className={`p-3 rounded-md ${isSafetyActive 
          ? 'bg-green-50 dark:bg-green-900/20' 
          : 'bg-muted'}`}>
          <div className="flex items-center mb-1">
            <ShieldAlert className={`h-4 w-4 mr-2 ${isSafetyActive 
              ? 'text-green-500 dark:text-green-400' 
              : 'text-gray-400 dark:text-gray-500'}`} />
            <span className="text-sm font-medium">Safety Systems:</span>
            <span className={`ml-auto text-xs font-medium ${isSafetyActive 
              ? 'text-green-500 dark:text-green-400' 
              : 'text-gray-400 dark:text-gray-500'}`}>
              {isSafetyActive ? 'Active' : 'Inactive'}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-x-2 gap-y-1 text-xs mt-1">
            <div className="flex items-center">
              <div className={`w-2 h-2 rounded-full mr-1 ${sensorData.isCollisionAvoidanceActive 
          ? 'bg-green-500 dark:bg-green-400' 
          : 'bg-gray-300 dark:bg-gray-600'}`}></div>
              <span>Collision Avoidance</span>
            </div>
            <div className="flex items-center">
              <div className={`w-2 h-2 rounded-full mr-1 ${sensorData.isEdgeDetectionActive 
          ? 'bg-green-500 dark:bg-green-400' 
          : 'bg-gray-300 dark:bg-gray-600'}`}></div>
              <span>Edge Detection</span>
            </div>
            <div className="flex items-center">
              <div className={`w-2 h-2 rounded-full mr-1 ${sensorData.isAutoStopActive 
          ? 'bg-green-500 dark:bg-green-400' 
          : 'bg-gray-300 dark:bg-gray-600'}`}></div>
              <span>Auto Stop</span>
            </div>
            <div className="flex items-center">
              <div className={`w-2 h-2 rounded-full mr-1 ${sensorData.isTrackingActive 
          ? 'bg-green-500 dark:bg-green-400' 
          : 'bg-gray-300 dark:bg-gray-600'}`}></div>
              <span>Tracking</span>
            </div>
            <div className="flex items-center">
              <div className={`w-2 h-2 rounded-full mr-1 ${sensorData.isCircuitModeActive 
          ? 'bg-green-500 dark:bg-green-400' 
          : 'bg-gray-300 dark:bg-gray-600'}`}></div>
              <span>Circuit Mode</span>
            </div>
          </div>
        </div>

        {/* Ultrasonic distance */}
        <div className="flex flex-col p-3 rounded-md bg-muted">
          <div className="flex items-center mb-1">
            <MoveHorizontal className="h-4 w-4 mr-2" />
            <span className="text-sm font-medium">Distance Sensor:</span>
            <span className={`ml-auto ${getDistanceColor(sensorData.ultrasonicDistance)}`}>
              {sensorData.ultrasonicDistance} cm
            </span>
          </div>
          <div className="relative w-full h-3 bg-gray-200 rounded-full overflow-hidden">
            <div 
              className={`absolute left-0 top-0 bottom-0 ${getDistanceColor(sensorData.ultrasonicDistance).replace('text-', 'bg-')}`}
              style={{ width: `${Math.min(100, Math.max(0, (sensorData.ultrasonicDistance / 100) * 100))}%` }}
            ></div>
          </div>
        </div>

        {/* Line sensors */}
        <div className="p-3 rounded-md bg-muted">
          <div className="flex items-center mb-2">
            <Car className="h-4 w-4 mr-2" />
            <span className="text-sm font-medium">Line Sensors:</span>
          </div>
          <div className="flex justify-between items-center">
            <div className="text-center">
              <div
                className={`w-6 h-6 mx-auto rounded-full ${
                  sensorData.lineFollowLeft < lineBlackThreshold
                    ? 'bg-black'
                    : 'bg-white border border-gray-300'
                }`}
              ></div>
              <div className="text-xs mt-1">{formatLineSensor(sensorData.lineFollowLeft)}</div>
              <div className="text-xs text-gray-500">Left</div>
            </div>
            <div className="text-center">
              <div
                className={`w-6 h-6 mx-auto rounded-full ${
                  sensorData.lineFollowMiddle < lineBlackThreshold
                    ? 'bg-black'
                    : 'bg-white border border-gray-300'
                }`}
              ></div>
              <div className="text-xs mt-1">{formatLineSensor(sensorData.lineFollowMiddle)}</div>
              <div className="text-xs text-gray-500">Middle</div>
            </div>
            <div className="text-center">
              <div
                className={`w-6 h-6 mx-auto rounded-full ${
                  sensorData.lineFollowRight < lineBlackThreshold
                    ? 'bg-black'
                    : 'bg-white border border-gray-300'
                }`}
              ></div>
              <div className="text-xs mt-1">{formatLineSensor(sensorData.lineFollowRight)}</div>
              <div className="text-xs text-gray-500">Right</div>
            </div>
          </div>
        </div>

        {/* Client status */}
        <div className="p-3 rounded-md bg-muted">
          <div className="flex items-center mb-1">
            <RadioTower className="h-4 w-4 mr-2" />
            <span className="text-sm font-medium">Client Status:</span>
          </div>
          <div className="flex items-center justify-between text-xs mt-1">
            <span>Connection:</span>
            <span className={`font-medium ${sensorData.clientConnected ? 'text-green-500' : 'text-red-500'}`}>
              {sensorData.clientConnected ? 'Connected' : 'Disconnected'}
            </span>
          </div>
          <div className="flex items-center justify-between text-xs mt-1">
            <span>Last Activity:</span>
            <span className="text-gray-500">
              {new Date(sensorData.lastClientActivity).toLocaleTimeString()}
            </span>
          </div>
        </div>

        {/* System Resource Usage */}
        <div className="p-3 rounded-md bg-muted">
        <div className="mb-4">
          <div className="flex items-center mb-1">
            <Cpu className="h-5 w-5" />
            <span className="text-sm font-medium ml-2">CPU Usage:</span>
            <span className={`ml-auto font-medium ${getResourceColor(sensorData.cpuUsage || 0)}`}>
              {sensorData.cpuUsage?.toFixed(1) || 0}%
            </span>
          </div>
          <Progress 
            value={sensorData.cpuUsage || 0} 
            className={`h-2 mb-2 ${getResourceProgressColor(sensorData.cpuUsage || 0)}`}
          />
          
          <div className="flex items-center mb-1">
            <MemoryStick className="h-5 w-5" />
            <span className="text-sm font-medium ml-2">RAM Usage:</span>
            <span className={`ml-auto font-medium ${getResourceColor(sensorData.ramUsage || 0)}`}>
              {sensorData.ramUsage?.toFixed(1) || 0}%
            </span>
          </div>
          <Progress 
            value={sensorData.ramUsage || 0} 
            className={`h-2 ${getResourceProgressColor(sensorData.ramUsage || 0)}`}
          />
        </div>
      </div>
      </div>
    </Card>
  );
}
