"use client";
import { useGamepadContext } from "@/contexts/GamepadContext";

interface JoystickDisplayProps {
  label: string;
  x: number;
  y: number;
  xAxisIndex: number;
  yAxisIndex: number;
}

export default function JoystickDisplay({
  label,
  x,
  y,
  xAxisIndex,
  yAxisIndex,
}: JoystickDisplayProps) {
  const { getActionForInput } = useGamepadContext();

  // Calculate dot position (centered is 50%, -1 to 1 range)
  const dotX = `${50 + x * 50}%`;
  const dotY = `${50 + y * 50}%`;

  // Find mapped actions for this joystick
  const xAction = getActionForInput("axis", xAxisIndex);
  const yAction = getActionForInput("axis", yAxisIndex);

  return (
    <div className="flex flex-col items-center">
      <div className="font-semibold mb-2">{label}</div>

      {/* Joystick visualization */}
      <div className="relative w-32 h-32 border border-border rounded-full bg-muted mb-2">
        {/* Center crosshair */}
        <div className="absolute top-1/2 left-0 w-full h-0.5 bg-muted-foreground/30"></div>
        <div className="absolute top-0 left-1/2 w-0.5 h-full bg-muted-foreground/30"></div>

        {/* Position dot */}
        <div
          className="absolute w-4 h-4 bg-primary rounded-full transform -translate-x-1/2 -translate-y-1/2 transition-all"
          style={{ left: dotX, top: dotY }}
        ></div>
      </div>

      {/* Position values */}
      <div className="text-xs text-muted-foreground">
        X: {x.toFixed(2)}, Y: {y.toFixed(2)}
      </div>

      {/* Mapped actions */}
      <div className="mt-1 text-xs text-primary">
        {xAction && <div>X → {xAction}</div>}
        {yAction && <div>Y → {yAction}</div>}
      </div>
    </div>
  );
}
