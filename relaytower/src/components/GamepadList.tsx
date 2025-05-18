"use client";
import { useGamepadContext } from "@/contexts/GamepadContext";
import { Button } from "./ui/button";
import { Card } from "./ui/card";

export function GamepadItem({ gamepad }: { gamepad: Gamepad }) {
  const { selectedGamepadId, selectGamepad } = useGamepadContext();
  const isSelected = gamepad.id === selectedGamepadId;

  return (
    <Card className={`p-4 my-2 ${isSelected ? "border-2 border-primary" : ""}`}>
      <div className="flex justify-between items-center gap-4">
        <div className="min-w-0 flex-1">
          <h3 className="font-medium truncate">{gamepad.id}</h3>
          <p className="text-sm text-gray-500 truncate">
            {gamepad.buttons.length} buttons, {gamepad.axes.length} axes
            {gamepad.mapping ? ` (${gamepad.mapping} mapping)` : ""}
          </p>
        </div>
        <Button
          onClick={() => selectGamepad(gamepad)}
          variant={isSelected ? "outline" : "default"}
          className="flex-shrink-0"
        >
          {isSelected ? "Selected" : "Use"}
        </Button>
      </div>
    </Card>
  );
}

export default function GamepadList() {
  const { availableGamepads, selectedGamepadId, selectGamepad } =
    useGamepadContext();

  return (
    <div className="w-full">
      <h2 className="text-xl font-bold mb-2">Available Gamepads</h2>

      {availableGamepads.length === 0 ? (
        <div className="text-center p-6 border rounded-xl">
          <p>No gamepads detected.</p>
          <p className="text-sm text-gray-500 mt-2">
            Connect a gamepad and press any button to activate it.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {availableGamepads.map((gamepad) => (
            <GamepadItem key={gamepad.id} gamepad={gamepad} />
          ))}

          {selectedGamepadId && (
            <Button
              variant="outline"
              className="mt-2"
              onClick={() => selectGamepad(null)}
            >
              Disconnect
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
