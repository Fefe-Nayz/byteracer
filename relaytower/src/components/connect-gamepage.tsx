"use client";

import { useGamepad } from "@/hooks/useGamepad";
import GamepadList from "./gamepad-list";
import { Card } from "./ui/card";

export default function ConnectGamepage() {
  const { gamepad, setGamepad } = useGamepad();

  return (
    <Card className="flex flex-col items-center p-6 w-full h-[800px]">
      {gamepad?.axes.map((button, index) => (
        <div key={index}>{button}</div>
      ))}
      <GamepadList />
    </Card>
  );
}
