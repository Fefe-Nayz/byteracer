"use client";
import { useGamepadContext } from "@/contexts/GamepadContext";
import { GamepadAxisInput } from "@/hooks/useGamepad";
import { Progress } from "./ui/progress";

export function AxisDisplay({ axis }: { axis: GamepadAxisInput }) {
  const { axisValues, getActionForInput } = useGamepadContext();

  const value = axisValues[axis.index] || 0;
  const mappedAction = getActionForInput("axis", axis.index);

  // Calculate position as percentage (0-100)
  const percentage = ((value + 1) / 2) * 100;

  return (
    <div className="p-3 border rounded-md">
      <div className="font-semibold">{axis.label}</div>
      <div className="text-sm mb-2">Value: {value.toFixed(2)}</div>

      <div className="relative">
        <Progress className="h-6 bg-secondary/50" value={percentage} />

        {/* Center marker */}
        <div className="absolute inset-y-0 w-0.5 bg-muted-foreground/50 left-1/2 z-10"></div>

        {/* Value indicator marker */}
      </div>

      {mappedAction && (
        <div className="text-xs text-primary mt-2">
          Mapped to: {mappedAction}
        </div>
      )}
    </div>
  );
}
