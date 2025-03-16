"use client";
import { useGamepadContext } from "@/contexts/GamepadContext";
import { GamepadAxisInput } from "@/hooks/useGamepad";

export function AxisDisplay({ axis }: { axis: GamepadAxisInput }) {
  const { axisValues, getActionForInput } = useGamepadContext();

  const value = axisValues[axis.index] || 0;
  const mappedAction = getActionForInput("axis", axis.index);

  // Calculate gradient position based on axis value (-1 to 1)
  const position = `${50 + value * 50}%`;

  return (
    <div className="p-3 border rounded-md">
      <div className="font-semibold">{axis.label}</div>
      <div className="text-sm mb-2">Value: {value.toFixed(2)}</div>

      <div className="relative h-6 bg-gray-200 rounded-full overflow-hidden">
        {/* Center line */}
        <div className="absolute h-full w-0.5 bg-gray-400 left-1/2 transform -translate-x-1/2"></div>

        {/* Value indicator */}
        <div
          className="absolute h-full w-1.5 bg-blue-600"
          style={{ left: position, transform: "translateX(-50%)" }}
        ></div>

        {/* Gradient background representing axis value */}
        <div
          className="absolute inset-0"
          style={{
            background: `linear-gradient(to right, #f87171 ${
              50 - value * 50
            }%, #86efac ${50 - value * 50}%)`,
            opacity: 0.5,
          }}
        ></div>
      </div>

      {mappedAction && (
        <div className="text-xs text-blue-600 mt-1">
          Mapped to: {mappedAction}
        </div>
      )}
    </div>
  );
}
