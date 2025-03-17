"use client";
import { useCallback, useState, useRef, useEffect } from "react";
import { ActionInfo } from "@/hooks/useGamepad";
import { useGamepadContext } from "@/contexts/GamepadContext";
import { Button } from "./ui/button";
import { Switch } from "./ui/switch";
import { Label } from "./ui/label";

export default function AxisConfigSlider({ action }: { action: ActionInfo }) {
  const { mappings, setAxisConfig, getRawAxisValue, getAxisValueForAction } =
    useGamepadContext();

  const mapping = mappings[action.key];
  const axisConfig = mapping?.axisConfig || {
    min: -1.0,
    max: 1.0,
    inverted: false,
    normalize: "full",
  };

  // State to track which handle is being dragged
  const [activeDrag, setActiveDrag] = useState<"min" | "max" | null>(null);

  // Reference to the container for calculating positions
  const sliderRef = useRef<HTMLDivElement>(null);

  // Current raw value from joystick
  const rawValue = getRawAxisValue?.(action.key) ?? 0;

  // Normalized value after applying config
  const normalizedValue = getAxisValueForAction?.(action.key, true) ?? 0;

  // Convert from -1..1 range to 0..100 for slider UI
  const minPos = ((axisConfig.min + 1) / 2) * 100;
  const maxPos = ((axisConfig.max + 1) / 2) * 100;

  // Raw value position (0-100)
  const rawPos = ((rawValue + 1) / 2) * 100;

  // Normalized value position (0-100)
  const normPos =
    axisConfig.normalize === "positive"
      ? normalizedValue * 100 // For positive mode (0-1 → 0-100)
      : ((normalizedValue + 1) / 2) * 100; // For full mode (-1,1 → 0-100)

  // Handle mouse down to start dragging
  const startDrag = useCallback((type: "min" | "max", e: React.MouseEvent) => {
    e.preventDefault();
    setActiveDrag(type);
  }, []);

  // Handle drag movement and slider value updates
  useEffect(() => {
    if (!activeDrag) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (!sliderRef.current) return;

      // Get slider bounds
      const rect = sliderRef.current.getBoundingClientRect();

      // Calculate position as percentage (0-100)
      const percentage = Math.max(
        0,
        Math.min(100, ((e.clientX - rect.left) / rect.width) * 100)
      );

      // Convert to -1..1 range
      const value = parseFloat((percentage / 50 - 1).toFixed(2)); // Round to 2 decimal places

      // Update the appropriate value based on what's being dragged
      const newConfig = { ...axisConfig };

      switch (activeDrag) {
        case "min":
          // Ensure min doesn't exceed max
          newConfig.min = parseFloat(
            Math.min(value, axisConfig.max - 0.05).toFixed(2)
          );
          break;
        case "max":
          // Ensure max doesn't fall below min
          newConfig.max = parseFloat(
            Math.max(value, axisConfig.min + 0.05).toFixed(2)
          );
          break;
      }

      // Update the axis configuration
      setAxisConfig(action.key, newConfig);
    };

    const handleMouseUp = () => {
      setActiveDrag(null);
    };

    // Add event listeners
    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [activeDrag, axisConfig, action.key, setAxisConfig]);

  // Toggle inversion
  const toggleInverted = useCallback(() => {
    setAxisConfig(action.key, {
      ...axisConfig,
      inverted: !axisConfig.inverted,
    });
  }, [action.key, axisConfig, setAxisConfig]);

  // Toggle normalization mode
  const toggleNormalization = useCallback(() => {
    setAxisConfig(action.key, {
      ...axisConfig,
      normalize: axisConfig.normalize === "full" ? "positive" : "full",
    });
  }, [action.key, axisConfig, setAxisConfig]);

  // Reset to defaults
  const resetToDefaults = useCallback(() => {
    const defaultConfig = {
      min: parseFloat((action.axisConfig?.defaultMin || -1.0).toFixed(2)),
      max: parseFloat((action.axisConfig?.defaultMax || 1.0).toFixed(2)),
      inverted: action.axisConfig?.inverted || false,
      normalize: action.axisConfig?.normalize || "full",
    };
    setAxisConfig(action.key, defaultConfig);
  }, [action, setAxisConfig]);

  // For the inversion function
  const invertAxis = useCallback(() => {
    const newConfig = {
      ...axisConfig,
      min: parseFloat(axisConfig.max.toFixed(2)),
      max: parseFloat(axisConfig.min.toFixed(2)),
      inverted: !axisConfig.inverted,
    };
    setAxisConfig(action.key, newConfig);
  }, [action.key, axisConfig, setAxisConfig]);

  return (
    <div className="mt-4 space-y-3">
      <div className="text-xs font-medium">Axis Configuration</div>

      {/* Raw Input Visualizer */}
      <div className="space-y-1">
        <div className="flex justify-between text-xs">
          <span>Raw Input:</span>
          <span>{rawValue.toFixed(2)}</span>
        </div>
        <div className="h-2 bg-gray-200 rounded-full relative">
          {/* Center indicator */}
          <div className="absolute h-full w-0.5 bg-gray-500 left-1/2"></div>
          {/* Raw value indicator */}
          <div
            className="absolute h-full w-2 bg-blue-500 rounded-full"
            style={{ left: `${rawPos}%`, transform: "translateX(-50%)" }}
          ></div>
        </div>
      </div>

      {/* Range Configuration Slider */}
      <div className="space-y-1">
        <div className="flex justify-between text-xs">
          <span>Range Config:</span>
          <span>
            Min: {axisConfig.min.toFixed(2)} | Max: {axisConfig.max.toFixed(2)}
          </span>
        </div>
        <div
          ref={sliderRef}
          className="h-10 bg-gray-100 rounded-full relative cursor-pointer"
        >
          {/* Center indicator (hardware center at 0) */}
          <div className="absolute h-full w-0.5 bg-gray-500 left-1/2"></div>

          {/* Range area visualization */}
          <div
            className="absolute h-full bg-blue-200 rounded-full"
            style={{ left: `${minPos}%`, width: `${maxPos - minPos}%` }}
          ></div>

          {/* Min handle */}
          <div
            className={`absolute h-full w-3 ${
              activeDrag === "min" ? "bg-red-700" : "bg-red-500"
            } rounded-full cursor-pointer top-0 bottom-0 z-10`}
            style={{ left: `${minPos}%`, transform: "translateX(-50%)" }}
            onMouseDown={(e) => startDrag("min", e)}
          ></div>

          {/* Max handle */}
          <div
            className={`absolute h-full w-3 ${
              activeDrag === "max" ? "bg-green-700" : "bg-green-500"
            } rounded-full cursor-pointer top-0 bottom-0 z-10`}
            style={{ left: `${maxPos}%`, transform: "translateX(-50%)" }}
            onMouseDown={(e) => startDrag("max", e)}
          ></div>
        </div>
      </div>

      {/* Output Visualization */}
      <div className="space-y-1">
        <div className="flex justify-between text-xs">
          <span>Normalized Output:</span>
          <span>{normalizedValue.toFixed(2)}</span>
        </div>
        <div className="h-2 bg-gray-200 rounded-full relative">
          {axisConfig.normalize === "full" && (
            /* Center indicator (only for full normalization) */
            <div className="absolute h-full w-0.5 bg-gray-500 left-1/2"></div>
          )}
          {/* Normalized value indicator */}
          <div
            className="absolute h-full w-2 bg-green-600 rounded-full"
            style={{ left: `${normPos}%`, transform: "translateX(-50%)" }}
          ></div>
        </div>
      </div>

      {/* Configuration Options */}
      <div className="space-y-2">
        <div className="flex items-center space-x-2">
          <Switch
            checked={axisConfig.inverted}
            onCheckedChange={toggleInverted}
            id="invert-axis"
          />
          <Label htmlFor="invert-axis">Invert Axis</Label>
        </div>

        <div className="flex items-center space-x-2">
          <Switch
            checked={axisConfig.normalize === "positive"}
            onCheckedChange={toggleNormalization}
            id="normalize-mode"
          />
          <Label htmlFor="normalize-mode">
            {axisConfig.normalize === "positive"
              ? "Positive Only (0 to 1)"
              : "Full Range (-1 to 1)"}
          </Label>
        </div>
      </div>

      {/* Reset Button */}
      <Button
        variant="outline"
        size="sm"
        onClick={resetToDefaults}
        className="w-full"
      >
        Reset to Defaults
      </Button>
    </div>
  );
}
