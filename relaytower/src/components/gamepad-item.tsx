"use client";

import { useGamepad } from "@/hooks/useGamepad";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card } from "./ui/card";

export default function GamepadItem({ gamepad }: { gamepad: Gamepad }) {
  const { setGamepad, gamepad: currentGamepad } = useGamepad();

  function selectGamepad() {
    setGamepad(gamepad);
    console.log("Gamepad selected", gamepad);
  }

  return (
    <Card className="flex flex-row items-center p-2 gap-2">
      {/* Gamepad Icon */}
      {/* <div></div> */}

      {/* Gamepad Info */}
      <div className="flex gap-2">
        <p className="font-semibold">{gamepad.id}</p>
        {gamepad.id === currentGamepad?.id && <Badge>Selectionné</Badge>}
      </div>

      <div>
        <Button onClick={() => selectGamepad()}>Utiliser</Button>
      </div>
    </Card>
  );
}
