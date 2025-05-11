"use client";
import {
  useWebSocket,
  RobotSettings as RobotSettingsType,
} from "@/contexts/WebSocketContext";
import { useState, useEffect } from "react";
import { Card } from "./ui/card";
import { Slider } from "./ui/slider";
import { Switch } from "./ui/switch";
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
  Volume2,
  Megaphone,
  Camera,
  AlertTriangle,
  PersonStanding,
  TrafficCone,
  BarChart,
  Gamepad2,
  Repeat,
  GitBranch,
  BrainCircuit,
  ShieldAlert,
  Battery,
} from "lucide-react";

export default function RobotSettings() {
  const {
    status,
    settings,
    updateSettings,
    requestSettings,
    resetSettings,
    startCalibration,
    stopCalibration,
    testCalibration,
    startTestCalibrateMotors,
    stopTestCalibrateMotors,
  } = useWebSocket();

  // Local state for settings (to avoid constant updates)
  const [localSettings, setLocalSettings] = useState<RobotSettingsType | null>(
    null
  );
  const [saveStatus, setSaveStatus] = useState<
    "idle" | "saving" | "saved" | "error"
  >("idle");
  const [isCalibrating, setIsCalibrating] = useState(false);
  const [lastCalibClick, setLastCalibClick] = useState<number | null>(null);

  // Update local settings when we get them from the server
  useEffect(() => {
    if (settings) {
      setLocalSettings(settings);
      console.log("Received settings:", settings);
    }

    if (saveStatus === "saving") {
      setSaveStatus("saved");
      setTimeout(() => setSaveStatus("idle"), 2000);
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
    setLocalSettings((prev) => {
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

    // On settings save, the app will send the updated settings to the robot so we change the status to "saved" after receiving the new settings response
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
        <h3 className="font-bold mb-4">AI Settings</h3>

        <div className="space-y-6">
          {/* Settings group for pause threshold, distance, confidence, turn time */}
          <div className="space-y-4">
            {/* Speak Pause Threshold */}
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span>Speak Pause Threshold</span>
                <span>{localSettings.ai.speak_pause_threshold}</span>
              </div>
              <Slider
                value={[localSettings.ai.speak_pause_threshold]}
                min={0.1}
                max={5}
                step={0.01}
                disabled={!localSettings.ai.speak_pause_threshold}
                onValueChange={(value) =>
                  updateSetting("ai", "speak_pause_threshold", value[0])
                }
              />
            </div>

            {/* Action Distance */}
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span>
                  Action Distance (cm){" "}
                  <span className="text-xs text-gray-500">
                    (Distance to act on detected objects)
                  </span>
                </span>
                <span>{localSettings.ai.distance_threshold_cm}</span>
              </div>
              <Slider
                value={[localSettings.ai.distance_threshold_cm || 30]}
                min={10}
                max={100}
                step={1}
                onValueChange={(value) =>
                  updateSetting("ai", "distance_threshold_cm", value[0])
                }
              />
            </div>

            {/* YOLO Confidence */}
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span>YOLO Confidence Threshold</span>
                <span>{localSettings.ai.yolo_confidence || 0.5}</span>
              </div>
              <Slider
                value={[localSettings.ai.yolo_confidence || 0.5]}
                min={0.1}
                max={0.9}
                step={0.05}
                onValueChange={(value) =>
                  updateSetting("ai", "yolo_confidence", value[0])
                }
              />
              <div className="text-xs text-muted-foreground mt-1">
                Lower values will detect more objects but with more false
                positives.
              </div>
            </div>

            {/* Turn Time */}
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span>Turn Time </span>
                <span>{localSettings.ai.turn_time}</span>
              </div>
              <Slider
                value={[localSettings.ai.turn_time]}
                min={0.5}
                max={10}
                step={0.1}
                disabled={!localSettings.ai.turn_time}
                onValueChange={(value) =>
                  updateSetting("ai", "turn_time", value[0])
                }
              />
              {/* Toggle button for starting/stopping calibration */}
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-2">
                  <span className="text-sm">Calibration</span>
                </div>
                <Button
                  variant={isCalibrating ? "destructive" : "default"}
                  onClick={() => {
                    const now = Date.now();
                    if (lastCalibClick && localSettings) {
                      const diffSeconds = (
                        (now - lastCalibClick) /
                        1000
                      ).toFixed(2);
                      // Update the turn_time slider
                      updateSetting("ai", "turn_time", parseFloat(diffSeconds));
                      setLastCalibClick(null);
                    } else {
                      setLastCalibClick(now);
                    }
                    if (isCalibrating) {
                      stopCalibration();
                      setIsCalibrating(false);
                    } else {
                      startCalibration();
                      setIsCalibrating(true);
                    }
                  }}
                >
                  {isCalibrating ? "Stop" : "Start"}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => {
                    testCalibration();
                  }}
                >
                  Test Calibration
                </Button>
              </div>
            </div>
          </div>

          {/* Motor Calibration Section */}
          <div className="pt-4 border-t space-y-4">
            <div className="text-sm font-medium mb-2">Motor Calibration</div>

            {/* Motor Balance */}
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span>Motor Balance</span>
                <span>{localSettings.ai.motor_balance}</span>
              </div>
              <Slider
                value={[localSettings.ai.motor_balance]}
                min={-50}
                max={50}
                step={1}
                onValueChange={(value) =>
                  updateSetting("ai", "motor_balance", value[0])
                }
              />
              <div className="text-xs text-gray-500 flex justify-between">
                <span>Boost Left</span>
                <span>Balanced</span>
                <span>Boost Right</span>
              </div>
            </div>
            {/* Motor Calibration Buttons */}
            <div className="flex justify-between mt-4">
              <Button
                variant="outline"
                onClick={() => startTestCalibrateMotors()}
              >
                Start Drive Test
              </Button>
              <Button
                variant="destructive"
                onClick={() => stopTestCalibrateMotors()}
              >
                Stop Drive Test
              </Button>
            </div>

            {/* Autonomous Speed Setting */}
            <div className="space-y-2 mt-4">
              <div className="flex justify-between text-xs">
                <span>Autonomous Driving Speed</span>
                <span>
                  {((localSettings.ai.autonomous_speed || 0.05) * 100).toFixed(
                    1
                  )}
                  %
                </span>
              </div>
              <Slider
                value={[(localSettings.ai.autonomous_speed || 0.05) * 100]}
                min={1}
                max={20}
                step={0.5}
                onValueChange={(value) =>
                  updateSetting("ai", "autonomous_speed", value[0] / 100)
                }
              />
              <div className="text-xs text-gray-500 flex justify-between">
                <span>Slow (1%)</span>
                <span>Default (5%)</span>
                <span>Fast (20%)</span>
              </div>
            </div>

            {/* Timing Settings */}
            <div className="mt-6 space-y-4">
              <h4 className="font-medium text-sm">Timing Settings</h4>

              {/* Right Turn Wait Time */}
              <div className="space-y-2">
                <div className="flex justify-between text-xs">
                  <span>Wait to Turn Time (sec)</span>
                  <span>
                    {(localSettings.ai.wait_to_turn_time || 2.0).toFixed(1)}s
                  </span>
                </div>
                <Slider
                  value={[localSettings.ai.wait_to_turn_time || 2.0]}
                  min={0.5}
                  max={5}
                  step={0.1}
                  onValueChange={(value) =>
                    updateSetting("ai", "wait_to_turn_time", value[0])
                  }
                />
              </div>

              {/* Stop Sign Wait Time */}
              <div className="space-y-2">
                <div className="flex justify-between text-xs">
                  <span>Stop Sign Wait Time (sec)</span>
                  <span>
                    {(localSettings.ai.stop_sign_wait_time || 2.0).toFixed(1)}s
                  </span>
                </div>
                <Slider
                  value={[localSettings.ai.stop_sign_wait_time || 2.0]}
                  min={0.5}
                  max={5}
                  step={0.1}
                  onValueChange={(value) =>
                    updateSetting("ai", "stop_sign_wait_time", value[0])
                  }
                />
              </div>

              {/* Stop Sign Ignore Time */}
              <div className="space-y-2">
                <div className="flex justify-between text-xs">
                  <span>Stop Sign Ignore Time (sec)</span>
                  <span>
                    {(localSettings.ai.stop_sign_ignore_time || 3.0).toFixed(1)}
                    s
                  </span>
                </div>
                <Slider
                  value={[localSettings.ai.stop_sign_ignore_time || 3.0]}
                  min={1}
                  max={10}
                  step={0.5}
                  onValueChange={(value) =>
                    updateSetting("ai", "stop_sign_ignore_time", value[0])
                  }
                />
              </div>

              {/* Traffic Light Ignore Time */}
              <div className="space-y-2">
                <div className="flex justify-between text-xs">
                  <span>Traffic Light Ignore Time (sec)</span>
                  <span>
                    {(
                      localSettings.ai.traffic_light_ignore_time || 3.0
                    ).toFixed(1)}
                    s
                  </span>
                </div>
                <Slider
                  value={[localSettings.ai.traffic_light_ignore_time || 3.0]}
                  min={1.0}
                  max={10.0}
                  step={0.1}
                  onValueChange={(value) =>
                    updateSetting("ai", "traffic_light_ignore_time", value[0])
                  }
                />
              </div>

              {/* Face Tracking Settings Section */}
              <div className="mt-6">
                <h4 className="font-medium text-sm">Face Tracking Settings</h4>

                {/* Target Face Area */}
                <div className="space-y-2 mt-2">
                  <div className="flex justify-between text-xs">
                    <span>Target Face Area (%)</span>
                    <span>
                      {(localSettings.ai.target_face_area || 10.0).toFixed(1)}%
                    </span>
                  </div>
                  <Slider
                    value={[localSettings.ai.target_face_area || 10.0]}
                    min={5.0}
                    max={30.0}
                    step={0.5}
                    onValueChange={(value) =>
                      updateSetting("ai", "target_face_area", value[0])
                    }
                  />
                  <div className="text-xs text-gray-500 flex justify-between">
                    <span>Small (5%)</span>
                    <span>Medium (10%)</span>
                    <span>Large (30%)</span>
                  </div>
                </div>

                {/* Forward Factor */}
                <div className="space-y-2 mt-4">
                  <div className="flex justify-between text-xs">
                    <span>Forward Factor</span>
                    <span>
                      {(localSettings.ai.forward_factor || 0.5).toFixed(2)}
                    </span>
                  </div>
                  <Slider
                    value={[localSettings.ai.forward_factor || 0.5]}
                    min={0.1}
                    max={1.0}
                    step={0.05}
                    onValueChange={(value) =>
                      updateSetting("ai", "forward_factor", value[0])
                    }
                  />
                  <div className="text-xs text-muted-foreground">
                    Adjusts how aggressively the robot moves toward the face
                  </div>
                </div>

                {/* Face Tracking Max Speed */}
                <div className="space-y-2 mt-4">
                  <div className="flex justify-between text-xs">
                    <span>Face Tracking Max Speed</span>
                    <span>
                      {(
                        (localSettings.ai.face_tracking_max_speed || 0.1) * 100
                      ).toFixed(1)}
                      %
                    </span>
                  </div>
                  <Slider
                    value={[
                      (localSettings.ai.face_tracking_max_speed || 0.1) * 100,
                    ]}
                    min={1}
                    max={20}
                    step={0.5}
                    onValueChange={(value) =>
                      updateSetting(
                        "ai",
                        "face_tracking_max_speed",
                        value[0] / 100
                      )
                    }
                  />
                </div>

                {/* Speed Dead Zone */}
                <div className="space-y-2 mt-4">
                  <div className="flex justify-between text-xs">
                    <span>Speed Dead Zone</span>
                    <span>
                      {(localSettings.ai.speed_dead_zone || 0.5).toFixed(2)}
                    </span>
                  </div>
                  <Slider
                    value={[localSettings.ai.speed_dead_zone || 0.5]}
                    min={0.0}
                    max={1.0}
                    step={0.05}
                    onValueChange={(value) =>
                      updateSetting("ai", "speed_dead_zone", value[0])
                    }
                  />
                  <div className="text-xs text-muted-foreground">
                    Smaller values make the robot more responsive
                  </div>
                </div>

                {/* Turn Factor */}
                <div className="space-y-2 mt-4">
                  <div className="flex justify-between text-xs">
                    <span>Turn Factor</span>
                    <span>
                      {(localSettings.ai.turn_factor || 35).toFixed(1)}
                    </span>
                  </div>
                  <Slider
                    value={[localSettings.ai.turn_factor || 35]}
                    min={10.0}
                    max={50.0}
                    step={1.0}
                    onValueChange={(value) =>
                      updateSetting("ai", "turn_factor", value[0])
                    }
                  />
                  <div className="text-xs text-muted-foreground">
                    Higher values make the robot turn more sharply
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </Card>

      <div className="gap-6 grid ">
        {/* Camera settings */}
        <Card className="p-4">
          <h3 className="font-bold mb-4">Camera Settings</h3>

          <div className="space-y-6">
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

              <div className="pt-2">
                <div className="mb-1 text-xs">Camera Resolution</div>
                <Select
                  value={
                    Array.isArray(localSettings.camera.camera_size)
                      ? `${localSettings.camera.camera_size[0]}x${localSettings.camera.camera_size[1]}`
                      : "1920x1080"
                  }
                  onValueChange={(value) => {
                    const [width, height] = value.split("x").map(Number);
                    updateSetting("camera", "camera_size", [width, height]);
                  }}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Select resolution" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="640x480">640 x 480 (SD)</SelectItem>
                    <SelectItem value="1280x720">1280 x 720 (HD)</SelectItem>
                    <SelectItem value="1920x1080">
                      1920 x 1080 (Full HD)
                    </SelectItem>
                  </SelectContent>
                </Select>
                <div className="mt-1 text-xs text-gray-500">
                  Higher resolution provides better image quality but may affect
                  performance.
                </div>
              </div>
            </div>
          </div>
        </Card>

        {/* AI settings */}
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
                  <span>
                    {localSettings.sound.sound_volume !== undefined
                      ? localSettings.sound.sound_volume
                      : 80}
                    %
                  </span>
                </div>
                <Slider
                  value={[
                    localSettings.sound.sound_volume !== undefined
                      ? localSettings.sound.sound_volume
                      : 80,
                  ]}
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
                    <span>
                      {localSettings.sound.driving_volume !== undefined
                        ? localSettings.sound.driving_volume
                        : 80}
                      %
                    </span>
                  </div>
                  <Slider
                    value={[
                      localSettings.sound.driving_volume !== undefined
                        ? localSettings.sound.driving_volume
                        : 80,
                    ]}
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
                    <span>
                      {localSettings.sound.alert_volume !== undefined
                        ? localSettings.sound.alert_volume
                        : 90}
                      %
                    </span>
                  </div>
                  <Slider
                    value={[
                      localSettings.sound.alert_volume !== undefined
                        ? localSettings.sound.alert_volume
                        : 90,
                    ]}
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
                    <span>
                      {localSettings.sound.custom_volume !== undefined
                        ? localSettings.sound.custom_volume
                        : 80}
                      %
                    </span>
                  </div>
                  <Slider
                    value={[
                      localSettings.sound.custom_volume !== undefined
                        ? localSettings.sound.custom_volume
                        : 80,
                    ]}
                    min={0}
                    max={100}
                    step={1}
                    disabled={!localSettings.sound.enabled}
                    onValueChange={(value) =>
                      updateSetting("sound", "custom_volume", value[0])
                    }
                  />
                </div>

                <div className="space-y-2">
                  <div className="flex justify-between text-xs">
                    <span>Push-to-Talk Voice</span>
                    <span>
                      {localSettings.sound.voice_volume !== undefined
                        ? localSettings.sound.voice_volume
                        : 95}
                      %
                    </span>
                  </div>
                  <Slider
                    value={[
                      localSettings.sound.voice_volume !== undefined
                        ? localSettings.sound.voice_volume
                        : 95,
                    ]}
                    min={0}
                    max={100}
                    step={1}
                    disabled={!localSettings.sound.enabled}
                    onValueChange={(value) =>
                      updateSetting("sound", "voice_volume", value[0])
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
                    <span>
                      {localSettings.sound.user_tts_volume !== undefined
                        ? localSettings.sound.user_tts_volume
                        : 80}
                      %
                    </span>
                  </div>
                  <Slider
                    value={[
                      localSettings.sound.user_tts_volume !== undefined
                        ? localSettings.sound.user_tts_volume
                        : 80,
                    ]}
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
                    <span>
                      {localSettings.sound.system_tts_volume !== undefined
                        ? localSettings.sound.system_tts_volume
                        : 90}
                      %
                    </span>
                  </div>
                  <Slider
                    value={[
                      localSettings.sound.system_tts_volume !== undefined
                        ? localSettings.sound.system_tts_volume
                        : 90,
                    ]}
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
                    <span>
                      {localSettings.sound.emergency_tts_volume !== undefined
                        ? localSettings.sound.emergency_tts_volume
                        : 95}
                      %
                    </span>
                  </div>
                  <Slider
                    value={[
                      localSettings.sound.emergency_tts_volume !== undefined
                        ? localSettings.sound.emergency_tts_volume
                        : 95,
                    ]}
                    min={0}
                    max={100}
                    step={1}
                    disabled={!localSettings.sound.tts_enabled}
                    onValueChange={(value) =>
                      updateSetting("sound", "emergency_tts_volume", value[0])
                    }
                  />
                </div>

                <div className="space-y-2">
                  <div className="flex justify-between text-xs">
                    <span>TTS Audio Gain (dB)</span>
                    <span>
                      {localSettings.sound.tts_audio_gain !== undefined
                        ? localSettings.sound.tts_audio_gain
                        : 6}
                    </span>
                  </div>
                  <Slider
                    value={[
                      localSettings.sound.tts_audio_gain !== undefined
                        ? localSettings.sound.tts_audio_gain
                        : 6,
                    ]}
                    min={0}
                    max={15}
                    step={1}
                    disabled={!localSettings.sound.tts_enabled}
                    onValueChange={(value) =>
                      updateSetting("sound", "tts_audio_gain", value[0])
                    }
                  />
                  <div className="text-xs text-muted-foreground mt-1">
                    Increase gain to boost TTS volume beyond normal levels
                  </div>
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
      </div>

      {/* Safety settings */}
      <Card className="p-4">
        <h3 className="font-bold mb-4">Safety Settings</h3>

        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <ShieldAlert className="h-4 w-4" />
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
              <span>
                Collision Distance{" "}
                <span className="text-xs text-gray-500">
                  (Distance to trigger emergency stop)
                </span>
              </span>
              <span>{localSettings.safety.collision_threshold} cm</span>
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

          {/* Safe Distance Buffer */}
          <div className="space-y-2">
            <div className="flex justify-between text-xs">
              <span>
                Safe Distance Buffer{" "}
                <span className="text-xs text-gray-500">
                  (Extra distance added to collision threshold)
                </span>
              </span>
              <span>{localSettings.safety.safe_distance_buffer || 10} cm</span>
            </div>
            <Slider
              value={[localSettings.safety.safe_distance_buffer || 10]}
              min={0}
              max={50}
              step={5}
              disabled={!localSettings.safety.collision_avoidance}
              onValueChange={(value) =>
                updateSetting("safety", "safe_distance_buffer", value[0])
              }
            />
          </div>

          {/* Emergency Cooldown */}
          <div className="space-y-2">
            <div className="flex justify-between text-xs">
              <span>
                Emergency Cooldown{" "}
                <span className="text-xs text-gray-500">
                  (Seconds between emergency checks)
                </span>
              </span>
              <span>
                {(localSettings.safety.emergency_cooldown || 0.1).toFixed(1)}s
              </span>
            </div>
            <Slider
              value={[localSettings.safety.emergency_cooldown || 0.1]}
              min={0.1}
              max={1.0}
              step={0.1}
              onValueChange={(value) =>
                updateSetting("safety", "emergency_cooldown", value[0])
              }
            />
          </div>

          {/* Edge Detection Section */}
          <div className="space-y-4 mt-6">
            <h4 className="font-medium text-sm">Edge Detection</h4>

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
                <span>
                  Edge Detection Threshold{" "}
                  <span className="text-xs text-gray-500">
                    (Lower is less sensitive)
                  </span>
                </span>
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

            {/* Edge Recovery Time */}
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span>
                  Edge Recovery Time{" "}
                  <span className="text-xs text-gray-500">
                    (Seconds to back up after edge clears)
                  </span>
                </span>
                <span>
                  {(localSettings.safety.edge_recovery_time || 0.5).toFixed(1)}s
                </span>
              </div>
              <Slider
                value={[localSettings.safety.edge_recovery_time || 0.5]}
                min={0.1}
                max={5.0}
                step={0.1}
                disabled={!localSettings.safety.edge_detection}
                onValueChange={(value) =>
                  updateSetting("safety", "edge_recovery_time", value[0])
                }
              />
            </div>
          </div>

          {/* Battery Safety Section */}
          <div className="space-y-4 mt-6">
            <h4 className="font-medium text-sm">Battery Safety</h4>

            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <Battery className="h-4 w-4" />
                <span className="text-sm">Battery Emergency</span>
              </div>
              <Switch
                checked={
                  localSettings.safety.battery_emergency_enabled !== false
                }
                onCheckedChange={(checked) =>
                  updateSetting("safety", "battery_emergency_enabled", checked)
                }
              />
            </div>

            {/* Low Battery Threshold */}
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span>Low Battery Threshold (%)</span>
                <span>{localSettings.safety.low_battery_threshold || 15}%</span>
              </div>
              <Slider
                value={[localSettings.safety.low_battery_threshold || 15]}
                min={5}
                max={30}
                step={1}
                disabled={
                  localSettings.safety.battery_emergency_enabled === false
                }
                onValueChange={(value) =>
                  updateSetting("safety", "low_battery_threshold", value[0])
                }
              />
            </div>

            {/* Low Battery Warning Interval */}
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span>
                  Warning Interval{" "}
                  <span className="text-xs text-gray-500">
                    (Seconds between low battery warnings)
                  </span>
                </span>
                <span>
                  {localSettings.safety.low_battery_warning_interval || 60}s
                </span>
              </div>
              <Slider
                value={[
                  localSettings.safety.low_battery_warning_interval || 60,
                ]}
                min={10}
                max={120}
                step={5}
                disabled={
                  localSettings.safety.battery_emergency_enabled === false
                }
                onValueChange={(value) =>
                  updateSetting(
                    "safety",
                    "low_battery_warning_interval",
                    value[0]
                  )
                }
              />
            </div>
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
                <span className="text-xs text-gray-500">
                  (differential steering)
                </span>
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
                <span className="text-xs text-gray-500">
                  (rotate on spot when stationary)
                </span>
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
                  localSettings.modes.normal_mode_enabled
                    ? "normal"
                    : localSettings.modes.tracking_enabled
                    ? "tracking"
                    : localSettings.modes.circuit_mode_enabled
                    ? "circuit"
                    : localSettings.modes.demo_mode_enabled
                    ? "demo"
                    : "normal" // Default fallback
                }
                onValueChange={(value) => {
                  // Update all mode settings based on selection
                  updateSetting(
                    "modes",
                    "normal_mode_enabled",
                    value === "normal"
                  );
                  updateSetting(
                    "modes",
                    "tracking_enabled",
                    value === "tracking"
                  );
                  updateSetting(
                    "modes",
                    "circuit_mode_enabled",
                    value === "circuit"
                  );
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
        <div>
        <h3 className="font-bold mb-4">LED Settings</h3>
        <div>
          <div className="mb-1 text-xs">Enable LED</div>
          <Switch
            checked={localSettings.led?.enabled || false}
            onCheckedChange={(checked) =>
              updateSetting("led", "enabled", checked)
            }
          />
        </div></div>
      </Card>

      {/* GitHub & System Settings - NEW CARD */}
      <Card className="p-4 md:col-span-2">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* GitHub settings */}
          <div className="space-y-4">
            <h3 className="font-bold mb-4">System Settings</h3>
            <div className="flex items-center space-x-2 mb-2">
              <GitBranch className="h-4 w-4" />
              <span className="text-sm font-medium">
                GitHub Repository Settings
              </span>
            </div>

            <div className="grid grid-cols-1 gap-4">
              <div>
                <div className="mb-1 text-xs">Repository URL</div>
                <Input
                  value={
                    localSettings.github?.repo_url ||
                    "https://github.com/nayzflux/byteracer.git"
                  }
                  onChange={(e) =>
                    updateSetting("github", "repo_url", e.target.value)
                  }
                  placeholder="https://github.com/user/repo.git"
                />
              </div>

              <div>
                <div className="mb-1 text-xs">Branch Name</div>
                <Input
                  value={localSettings.github?.branch || "working-2"}
                  onChange={(e) =>
                    updateSetting("github", "branch", e.target.value)
                  }
                  placeholder="main"
                />
              </div>
            </div>

            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <Repeat className="h-4 w-4" />
                <span className="text-sm">Auto Update on Boot</span>
              </div>
              <Switch
                checked={localSettings.github?.auto_update !== false}
                onCheckedChange={(checked) =>
                  updateSetting("github", "auto_update", checked)
                }
              />
            </div>
          </div>

          {/* API Settings */}
          <div className="space-y-4">
            <h3 className="font-bold mb-4">API Settings</h3>
            <div className="flex items-center space-x-2 mb-2">
              <BrainCircuit className="h-4 w-4" />
              <span className="text-sm font-medium">OpenAI Integration</span>
            </div>

            <div className="grid grid-cols-1 gap-4">
              <div>
                <div className="mb-1 text-xs">API Key</div>
                <Input
                  type="password"
                  value={localSettings.api?.openai_api_key || ""}
                  onChange={(e) =>
                    updateSetting("api", "openai_api_key", e.target.value)
                  }
                  placeholder="sk-..."
                />
                <div className="mt-1 text-xs text-muted-foreground">
                  Required for GPT voice commands and vision features
                </div>
              </div>
            </div>
          </div>
        </div>
      </Card>

      {/* Save buttons */}
      <div className="md:col-span-2 flex justify-end space-x-4">
        <Button variant="outline" onClick={discardChanges}>
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
