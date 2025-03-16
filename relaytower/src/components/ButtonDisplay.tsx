"use client";
import { useGamepadContext } from "@/contexts/GamepadContext";
import { GamepadButtonInput } from "@/hooks/useGamepad";

export function ButtonDisplay({ button }: { button: GamepadButtonInput }) {
  const { pressedInputs, getActionForInput } = useGamepadContext();

  const isPressed = pressedInputs.has(button.id);
  const mappedAction = getActionForInput("button", button.index);

  return (
    <div
      className={`p-3 border rounded-md text-center transition-colors ${
        isPressed ? "bg-green-200" : "bg-gray-100"
      }`}
    >
      <div className="font-semibold">{button.label}</div>
      <div className="text-sm">{isPressed ? "Pressed" : "Released"}</div>
      {mappedAction && (
        <div className="text-xs text-blue-600 mt-1">
          Mapped to: {mappedAction}
        </div>
      )}
    </div>
  );
}
