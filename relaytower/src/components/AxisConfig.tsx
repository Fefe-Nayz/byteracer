"use client";
import { useCallback } from "react";
import { ActionInfo } from "@/hooks/useGamepad";
import { useGamepadContext } from "@/contexts/GamepadContext";
import { Button } from "./ui/button";
import { Switch } from "./ui/switch";
import { Label } from "./ui/label";
import { DualRangeSlider } from "./ui/dual-range-slider";
import { Progress } from "./ui/progress";

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

  // Current raw value from joystick
  const rawValue = getRawAxisValue?.(action.key) ?? 0;

  // Normalized value after applying config
  const normalizedValue = getAxisValueForAction?.(action.key, true) ?? 0;

  // Convert values to 0-100 range for visualization
  const rawPercent = ((rawValue + 1) / 2) * 100;
  const normPercent =
    axisConfig.normalize === "positive"
      ? normalizedValue * 100 // 0-1 → 0-100%
      : ((normalizedValue + 1) / 2) * 100; // -1 to 1 → 0-100%

  // Update range configuration
  const handleRangeChange = useCallback(
    (values: number[]) => {
      if (values.length === 2) {
        setAxisConfig(action.key, {
          ...axisConfig,
          min: values[0],
          max: values[1],
        });
      }
    },
    [action.key, axisConfig, setAxisConfig]
  );

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

  // Format values for labels
  const formatValue = (value: number | undefined) => {
    return value !== undefined ? value.toFixed(2) : "";
  };

  return (
    <div className="mt-4 space-y-3">
      <div className="text-xs font-medium text-muted-foreground">
        Axis Configuration
      </div>

      {/* Raw Input Visualizer */}
      <div className="space-y-1">
        <div className="flex justify-between text-xs">
          <span>Raw Input:</span>
          <span>{rawValue.toFixed(2)}</span>
        </div>
        <div className="relative">
          <Progress className="h-2 bg-secondary/50" value={rawPercent} />
          <div className="absolute h-full w-0.5 bg-muted-foreground/50 left-1/2 top-0"></div>
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

        <DualRangeSlider
          min={-1}
          max={1}
          step={0.01}
          value={[axisConfig.min, axisConfig.max]}
          onValueChange={handleRangeChange}
          label={formatValue}
        />
      </div>

      {/* Output Visualization */}
      <div className="space-y-1">
        <div className="flex justify-between text-xs">
          <span>Normalized Output:</span>
          <span>{normalizedValue.toFixed(2)}</span>
        </div>
        <div className="relative">
          <Progress className="h-2 bg-secondary/50" value={normPercent} />

          {axisConfig.normalize === "full" && (
            <div className="absolute h-full w-0.5 bg-muted-foreground/50 left-1/2 top-0"></div>
          )}
        </div>
      </div>

      {/* Configuration Options */}
      <div className="space-y-2 pt-1">
        <div className="flex items-center space-x-2">
          <Switch
            checked={axisConfig.inverted}
            onCheckedChange={toggleInverted}
            id="invert-axis"
          />
          <Label htmlFor="invert-axis" className="text-sm">
            Invert Axis
          </Label>
        </div>

        <div className="flex items-center space-x-2">
          <Switch
            checked={axisConfig.normalize === "positive"}
            onCheckedChange={toggleNormalization}
            id="normalize-mode"
          />
          <Label htmlFor="normalize-mode" className="text-sm">
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
