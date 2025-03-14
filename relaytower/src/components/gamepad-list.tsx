"use client";

import { useEffect, useState } from "react";
import GamepadEmptyState from "./gamepad-empty-state";
import GamepadItem from "./gamepad-item";

export default function GamepadList() {
  const [gamepads, setGamepads] = useState<(Gamepad | null)[]>([]);

  useEffect(() => {
    const gampads = navigator.getGamepads();
    setGamepads(gampads);

    window.addEventListener("gamepadconnected", (event) => {
      setGamepads([...gamepads, event.gamepad]);
      console.log("Gamepad connected", event.gamepad);
    });

    window.addEventListener("gamepaddisconnected", (event) => {
      setGamepads(
        gamepads.filter((gamepad) => gamepad?.id !== event.gamepad.id)
      );
      console.log("Gamepad disconnected", event.gamepad);
    });

    return () => {
      window.removeEventListener("gamepadconnected", () => {});
      window.removeEventListener("gamepaddisconnected", () => {});
    };
  }, []);

  return (
    <div className="flex flex-col items-center justify-center gap-4">
      {gamepads.length === 0 ? (
        <GamepadEmptyState />
      ) : (
        gamepads.map((gamepad) => {
          if (gamepad) {
            return <GamepadItem key={gamepad.id} gamepad={gamepad} />;
          }
        })
      )}
    </div>
  );
}
