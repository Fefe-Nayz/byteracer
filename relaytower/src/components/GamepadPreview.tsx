"use client";
import { useGamepadContext } from "@/contexts/GamepadContext";
import { ButtonDisplay } from "./ButtonDisplay";
import { AxisDisplay } from "./AxisDisplay";
import JoystickDisplay from "./JoystickDisplay";
import ActionStatus from "./ActionStatus";
import RemapControls from "./RemapControls";
import { ACTIONS } from "@/hooks/useGamepad";
import { Card } from "./ui/card";

export default function GamepadPreview() {
  const { connected, gamepadInputs, axisValues, selectedGamepadId } =
    useGamepadContext();

  if (!connected || !selectedGamepadId) return null;

  // Create joystick pairs (usually axes 0-1 and 2-3 for left and right sticks)
  const joysticks = [];
  if (gamepadInputs.axes.length >= 2) {
    joysticks.push({
      name: "Left Stick",
      xAxis: 0,
      yAxis: 1,
      x: axisValues[0] || 0,
      y: axisValues[1] || 0,
    });
  }

  if (gamepadInputs.axes.length >= 4) {
    joysticks.push({
      name: "Right Stick",
      xAxis: 2,
      yAxis: 3,
      x: axisValues[2] || 0,
      y: axisValues[3] || 0,
    });
  }

  return (
    <Card className="p-6 w-full">
      <h2 className="text-xl font-bold mb-4">Gamepad Preview</h2>

      {/* Joysticks visualization */}
      {joysticks.length > 0 && (
        <div className="mb-6">
          <h3 className="text-lg font-semibold mb-2">Joysticks</h3>
          <div className="flex flex-wrap justify-center gap-6">
            {joysticks.map((stick) => (
              <JoystickDisplay
                key={stick.name}
                label={stick.name}
                x={stick.x}
                y={stick.y}
                xAxisIndex={stick.xAxis}
                yAxisIndex={stick.yAxis}
              />
            ))}
          </div>
        </div>
      )}

      {/* Buttons */}
      {gamepadInputs.buttons.length > 0 && (
        <div className="mb-6">
          <h3 className="text-lg font-semibold mb-2">Buttons</h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
            {gamepadInputs.buttons.map((button) => (
              <ButtonDisplay key={button.id} button={button} />
            ))}
          </div>
        </div>
      )}

      {/* Individual axes */}
      {gamepadInputs.axes.length > 0 && (
        <div className="mb-6">
          <h3 className="text-lg font-semibold mb-2">Axes</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {gamepadInputs.axes.map((axis) => (
              <AxisDisplay key={axis.id} axis={axis} />
            ))}
          </div>
        </div>
      )}

      {/* In-game actions status */}
      <div className="mb-6">
        <h3 className="text-lg font-semibold mb-2">In-Game Actions</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {ACTIONS.map((action) => (
            <ActionStatus key={action.key} action={action} />
          ))}
        </div>
      </div>

      {/* Remapping controls */}
      <RemapControls />
    </Card>
  );
}
