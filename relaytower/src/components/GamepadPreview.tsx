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

  // Dynamically create joystick pairs from available axes
  const joysticks = [];

  // Assume axes come in pairs (like X/Y for a stick)
  for (let i = 0; i < gamepadInputs.axes.length; i += 2) {
    // Make sure we have both X and Y axes
    if (i + 1 < gamepadInputs.axes.length) {
      // Get appropriate label based on index
      let name = "Joystick " + (i / 2 + 1);
      if (gamepadInputs.axes[i].label.includes("Left")) {
        name = "Left Stick";
      } else if (gamepadInputs.axes[i].label.includes("Right")) {
        name = "Right Stick";
      }

      joysticks.push({
        name,
        xAxis: i,
        yAxis: i + 1,
        x: axisValues[i] || 0,
        y: axisValues[i + 1] || 0,
      });
    }
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
