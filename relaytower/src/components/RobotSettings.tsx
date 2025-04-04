"use client";
import { useWebSocket, RobotSettings as RobotSettingsType } from "@/contexts/WebSocketContext";
import { useState, useEffect } from "react";
import { Card } from "./ui/card";
import { Slider } from "./ui/slider";
import { Switch } from "./ui/switch";
import { Button } from "./ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { 
  Volume2, Megaphone, Camera, AlertTriangle,
  PersonStanding, TrafficCone, BarChart, Gamepad2
} from "lucide-react";

export default function RobotSettings() {
  const { 
    status, 
    settings, 
    updateSettings, 
    requestSettings,
    resetSettings 
  } = useWebSocket();
  
  // Local state for settings (to avoid constant updates)
  const [localSettings, setLocalSettings] = useState<RobotSettingsType | null>(null);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  
  // Update local settings when we get them from the server
  useEffect(() => {
    if (settings) {
      setLocalSettings(settings);
      console.log("Received settings:", settings);
    }
  }, [settings]);
  
  // Request settings when component mounts or reconnects
  useEffect(() => {
    if (status === "connected") {
      requestSettings();
    }
  }, [status, requestSettings]);

  // If no settings or not connected, show placeholder
  if (!localSettings || status !== "connected") {
    return (
      <Card className="p-4">
        <h3 className="font-bold mb-3">Robot Settings</h3>
        <div className="text-sm text-gray-500 italic">
          {status === "connected" 
            ? "Loading settings..." 
            : "Connect to robot to view settings"}
        </div>
      </Card>
    );
  }
  
  // Update a specific setting
  const updateSetting = (
    category: keyof RobotSettingsType, 
    key: string, 
    value: unknown
  ) => {
    setLocalSettings(prev => {
      if (!prev) return prev;
      
      // Create deep copy of the settings
      const updated = JSON.parse(JSON.stringify(prev));
      
      // Update the specific setting
      updated[category][key] = value;

      console.log("Updated settings:", updated);
      
      return updated;
    });
  };
  
  // Save settings to the robot
  const saveSettings = () => {
    if (!localSettings) return;
    
    setSaveStatus("saving");
    updateSettings(localSettings);
    
    // Simulate a response (in a real app, wait for a success/error response)
    setTimeout(() => {
      setSaveStatus("saved");
      setTimeout(() => setSaveStatus("idle"), 2000);
    }, 800);
  };
  
  // Discard changes
  const discardChanges = () => {
    if (settings) {
      setLocalSettings(settings);
    }
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
      {/* Sound settings */}
      <Card className="p-4">
        <h3 className="font-bold mb-4">Sound Settings</h3>
        
        <div className="space-y-6">
          {/* Master volume */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <Volume2 className="h-4 w-4" />
                <span className="text-sm font-medium">Master Volume</span>
              </div>
              <Switch 
                checked={localSettings.sound.enabled}
                onCheckedChange={(checked) => 
                  updateSetting("sound", "enabled", checked)
                }
              />
            </div>
            
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span>Master Volume</span>
                <span>{localSettings.sound.volume}%</span>
              </div>
              <Slider 
                value={[localSettings.sound.volume]}
                min={0}
                max={100}
                step={1}
                disabled={!localSettings.sound.enabled}
                onValueChange={(value) => 
                  updateSetting("sound", "volume", value[0])
                }
              />
            </div>
          </div>
          
          {/* Sound effects section */}
          <div className="pt-4 border-t space-y-4">
            <div className="text-sm font-medium mb-2">Sound Effects</div>
            
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span>Effects Master Volume</span>
                <span>{localSettings.sound.sound_volume !== undefined ? localSettings.sound.sound_volume : 80}%</span>
              </div>
              <Slider 
                value={[localSettings.sound.sound_volume !== undefined ? localSettings.sound.sound_volume : 80]}
                min={0}
                max={100}
                step={1}
                disabled={!localSettings.sound.enabled}
                onValueChange={(value) => 
                  updateSetting("sound", "sound_volume", value[0])
                }
              />
            </div>
            
            <div className="pl-4 pt-2 space-y-3">
              <div className="space-y-2">
                <div className="flex justify-between text-xs">
                  <span>Driving Sounds</span>
                  <span>{localSettings.sound.driving_volume !== undefined ? localSettings.sound.driving_volume : 80}%</span>
                </div>
                <Slider 
                  value={[localSettings.sound.driving_volume !== undefined ? localSettings.sound.driving_volume : 80]}
                  min={0}
                  max={100}
                  step={1}
                  disabled={!localSettings.sound.enabled}
                  onValueChange={(value) => 
                    updateSetting("sound", "driving_volume", value[0])
                  }
                />
              </div>
              
              <div className="space-y-2">
                <div className="flex justify-between text-xs">
                  <span>Alert Sounds</span>
                  <span>{localSettings.sound.alert_volume !== undefined ? localSettings.sound.alert_volume : 90}%</span>
                </div>
                <Slider 
                  value={[localSettings.sound.alert_volume !== undefined ? localSettings.sound.alert_volume : 90]}
                  min={0}
                  max={100}
                  step={1}
                  disabled={!localSettings.sound.enabled}
                  onValueChange={(value) => 
                    updateSetting("sound", "alert_volume", value[0])
                  }
                />
              </div>
              
              <div className="space-y-2">
                <div className="flex justify-between text-xs">
                  <span>Custom Sounds</span>
                  <span>{localSettings.sound.custom_volume !== undefined ? localSettings.sound.custom_volume : 80}%</span>
                </div>
                <Slider 
                  value={[localSettings.sound.custom_volume !== undefined ? localSettings.sound.custom_volume : 80]}
                  min={0}
                  max={100}
                  step={1}
                  disabled={!localSettings.sound.enabled}
                  onValueChange={(value) => 
                    updateSetting("sound", "custom_volume", value[0])
                  }
                />
              </div>
            </div>
          </div>
          
          {/* TTS settings */}
          <div className="pt-4 border-t space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <Megaphone className="h-4 w-4" />
                <span className="text-sm font-medium">Text-to-Speech</span>
              </div>
              <Switch 
                checked={localSettings.sound.tts_enabled}
                onCheckedChange={(checked) => 
                  updateSetting("sound", "tts_enabled", checked)
                }
              />
            </div>
            
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span>TTS Master Volume</span>
                <span>{localSettings.sound.tts_volume}%</span>
              </div>
              <Slider 
                value={[localSettings.sound.tts_volume]}
                min={0}
                max={100}
                step={1}
                disabled={!localSettings.sound.tts_enabled}
                onValueChange={(value) => 
                  updateSetting("sound", "tts_volume", value[0])
                }
              />
            </div>
            
            <div className="pl-4 pt-2 space-y-3">
              <div className="space-y-2">
                <div className="flex justify-between text-xs">
                  <span>User TTS</span>
                  <span>{localSettings.sound.user_tts_volume !== undefined ? localSettings.sound.user_tts_volume : 80}%</span>
                </div>
                <Slider 
                  value={[localSettings.sound.user_tts_volume !== undefined ? localSettings.sound.user_tts_volume : 80]}
                  min={0}
                  max={100}
                  step={1}
                  disabled={!localSettings.sound.tts_enabled}
                  onValueChange={(value) => 
                    updateSetting("sound", "user_tts_volume", value[0])
                  }
                />
              </div>
              
              <div className="space-y-2">
                <div className="flex justify-between text-xs">
                  <span>System TTS</span>
                  <span>{localSettings.sound.system_tts_volume !== undefined ? localSettings.sound.system_tts_volume : 90}%</span>
                </div>
                <Slider 
                  value={[localSettings.sound.system_tts_volume !== undefined ? localSettings.sound.system_tts_volume : 90]}
                  min={0}
                  max={100}
                  step={1}
                  disabled={!localSettings.sound.tts_enabled}
                  onValueChange={(value) => 
                    updateSetting("sound", "system_tts_volume", value[0])
                  }
                />
              </div>
              
              <div className="space-y-2">
                <div className="flex justify-between text-xs">
                  <span>Emergency TTS</span>
                  <span>{localSettings.sound.emergency_tts_volume !== undefined ? localSettings.sound.emergency_tts_volume : 95}%</span>
                </div>
                <Slider 
                  value={[localSettings.sound.emergency_tts_volume !== undefined ? localSettings.sound.emergency_tts_volume : 95]}
                  min={0}
                  max={100}
                  step={1}
                  disabled={!localSettings.sound.tts_enabled}
                  onValueChange={(value) => 
                    updateSetting("sound", "emergency_tts_volume", value[0])
                  }
                />
              </div>
            </div>
            
            <div>
              <div className="mb-1 text-xs">TTS Language</div>
              <Select 
                value={localSettings.sound.tts_language} 
                onValueChange={(value) => 
                  updateSetting("sound", "tts_language", value)
                }
                disabled={!localSettings.sound.tts_enabled}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Select language" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="en-US">English (US)</SelectItem>
                  <SelectItem value="en-GB">English (UK)</SelectItem>
                  <SelectItem value="fr-FR">French</SelectItem>
                  <SelectItem value="de-DE">German</SelectItem>
                  <SelectItem value="es-ES">Spanish</SelectItem>
                  <SelectItem value="it-IT">Italian</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>
      </Card>
      
      {/* Camera settings */}
      <Card className="p-4">
        <h3 className="font-bold mb-4">Camera Settings</h3>
        
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <Camera className="h-4 w-4" />
              <span className="text-sm">Vertical Flip</span>
            </div>
            <Switch 
              checked={localSettings.camera.vflip}
              onCheckedChange={(checked) => 
                updateSetting("camera", "vflip", checked)
              }
            />
          </div>
          
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <Camera className="h-4 w-4" />
              <span className="text-sm">Horizontal Flip</span>
            </div>
            <Switch 
              checked={localSettings.camera.hflip}
              onCheckedChange={(checked) => 
                updateSetting("camera", "hflip", checked)
              }
            />
          </div>
          
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <Camera className="h-4 w-4" />
              <span className="text-sm">Local Display</span>
              <span className="text-xs text-gray-500">(if connected)</span>
            </div>
            <Switch 
              checked={localSettings.camera.local_display}
              onCheckedChange={(checked) => 
                updateSetting("camera", "local_display", checked)
              }
            />
          </div>
          
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <Camera className="h-4 w-4" />
              <span className="text-sm">Web Display</span>
            </div>
            <Switch 
              checked={localSettings.camera.web_display}
              onCheckedChange={(checked) => 
                updateSetting("camera", "web_display", checked)
              }
            />
          </div>
        </div>
      </Card>
      
      {/* Safety settings */}
      <Card className="p-4">
        <h3 className="font-bold mb-4">Safety Settings</h3>
        
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <AlertTriangle className="h-4 w-4" />
              <span className="text-sm">Collision Avoidance</span>
            </div>
            <Switch 
              checked={localSettings.safety.collision_avoidance}
              onCheckedChange={(checked) => 
                updateSetting("safety", "collision_avoidance", checked)
              }
            />
          </div>
          
          <div className="space-y-2">
            <div className="flex justify-between text-xs">
              <span>Collision Threshold (cm)</span>
              <span>{localSettings.safety.collision_threshold}</span>
            </div>
            <Slider 
              value={[localSettings.safety.collision_threshold]}
              min={10}
              max={100}
              step={5}
              disabled={!localSettings.safety.collision_avoidance}
              onValueChange={(value) => 
                updateSetting("safety", "collision_threshold", value[0])
              }
            />
          </div>
          
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <AlertTriangle className="h-4 w-4" />
              <span className="text-sm">Edge Detection</span>
            </div>
            <Switch 
              checked={localSettings.safety.edge_detection}
              onCheckedChange={(checked) => 
                updateSetting("safety", "edge_detection", checked)
              }
            />
          </div>
          
          <div className="space-y-2">
            <div className="flex justify-between text-xs">
              <span>Edge Detection Threshold <span className="text-xs text-gray-500">(Lower is less sensitive)</span></span>
              <span>{localSettings.safety.edge_threshold}</span>
            </div>
            <Slider 
              value={[localSettings.safety.edge_threshold]}
              min={0.1}
              max={0.9}
              step={0.05}
              disabled={!localSettings.safety.edge_detection}
              onValueChange={(value) => 
                updateSetting("safety", "edge_threshold", value[0])
              }
            />
          </div>
          
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <AlertTriangle className="h-4 w-4" />
              <span className="text-sm">Auto-Stop on Timeout</span>
            </div>
            <Switch 
              checked={localSettings.safety.auto_stop}
              onCheckedChange={(checked) => 
                updateSetting("safety", "auto_stop", checked)
              }
            />
          </div>
          
          <div className="space-y-2">
            <div className="flex justify-between text-xs">
              <span>Client Timeout (seconds)</span>
              <span>{localSettings.safety.client_timeout}</span>
            </div>
            <Slider 
              value={[localSettings.safety.client_timeout]}
              min={1}
              max={30}
              step={1}
              disabled={!localSettings.safety.auto_stop}
              onValueChange={(value) => 
                updateSetting("safety", "client_timeout", value[0])
              }
            />
          </div>
        </div>
      </Card>
      
      {/* Drive & Mode settings */}
      <Card className="p-4">
        <div className="mb-6">
          <h3 className="font-bold mb-4">Drive Settings</h3>
          
          <div className="space-y-4">
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span>Max Speed (%)</span>
                <span>{localSettings.drive.max_speed}</span>
              </div>
              <Slider 
                value={[localSettings.drive.max_speed]}
                min={10}
                max={100}
                step={5}
                onValueChange={(value) => 
                  updateSetting("drive", "max_speed", value[0])
                }
              />
            </div>
            
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span>Max Turn Angle (%)</span>
                <span>{localSettings.drive.max_turn_angle}</span>
              </div>
              <Slider 
                value={[localSettings.drive.max_turn_angle]}
                min={10}
                max={100}
                step={5}
                onValueChange={(value) => 
                  updateSetting("drive", "max_turn_angle", value[0])
                }
              />
            </div>
            
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span>Acceleration Factor</span>
                <span>{localSettings.drive.acceleration_factor}</span>
              </div>
              <Slider 
                value={[localSettings.drive.acceleration_factor]}
                min={0.1}
                max={1.0}
                step={0.05}
                onValueChange={(value) => 
                  updateSetting("drive", "acceleration_factor", value[0])
                }
              />
            </div>
            
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <span className="text-sm">Enhanced Turning</span>
                <span className="text-xs text-gray-500">(differential steering)</span>
              </div>
              <Switch 
                checked={localSettings.drive.enhanced_turning}
                onCheckedChange={(checked) => 
                  updateSetting("drive", "enhanced_turning", checked)
                }
              />
            </div>
            
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <span className="text-sm">Turn in Place</span>
                <span className="text-xs text-gray-500">(rotate on spot when stationary)</span>
              </div>
              <Switch 
                checked={localSettings.drive.turn_in_place}
                onCheckedChange={(checked) => 
                  updateSetting("drive", "turn_in_place", checked)
                }
              />
            </div>
          </div>
        </div>
        
        <div>
          <h3 className="font-bold mb-4">Mode Settings</h3>
          
          <div className="space-y-4">
            <div className="space-y-2">
              <div className="flex items-center space-x-2 mb-2">
                <span className="text-sm font-medium">Operation Mode</span>
                <span className="text-xs text-gray-500">(select one)</span>
              </div>
              
              <Select 
                value={
                  localSettings.modes.normal_mode_enabled ? "normal" :
                  localSettings.modes.tracking_enabled ? "tracking" :
                  localSettings.modes.circuit_mode_enabled ? "circuit" :
                  localSettings.modes.demo_mode_enabled ? "demo" :
                  "normal" // Default fallback
                } 
                onValueChange={(value) => {
                  // Update all mode settings based on selection
                  updateSetting("modes", "normal_mode_enabled", value === "normal");
                  updateSetting("modes", "tracking_enabled", value === "tracking");
                  updateSetting("modes", "circuit_mode_enabled", value === "circuit");
                  updateSetting("modes", "demo_mode_enabled", value === "demo");
                }}
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
          </div>
        </div>
      </Card>
      
      {/* Save buttons */}
      <div className="md:col-span-2 flex justify-end space-x-4">
        <Button 
          variant="outline" 
          onClick={discardChanges}
        >
          Discard Changes
        </Button>
        
        <Button 
          variant="destructive"
          onClick={() => {
              resetSettings();
              setSaveStatus("idle");
          }}
        >
          Reset to Defaults
        </Button>
        
        <Button 
          onClick={saveSettings}
          disabled={saveStatus === "saving"}
          className="min-w-[100px]"
        >
          {saveStatus === "idle" && "Save Settings"}
          {saveStatus === "saving" && "Saving..."}
          {saveStatus === "saved" && "Saved!"}
          {saveStatus === "error" && "Error!"}
        </Button>
      </div>
    </div>
  );
}