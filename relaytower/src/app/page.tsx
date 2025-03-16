"use client";
import { useState, useEffect } from "react";
import { GamepadProvider } from "@/contexts/GamepadContext";
import { useGamepadContext } from "@/contexts/GamepadContext";
import GamepadList from "@/components/GamepadList";
import GamepadPreview from "@/components/GamepadPreview";
import { Card } from "@/components/ui/card";
import WebSocketStatus from "@/components/WebSocketStatus";
import DebugState from "@/components/DebugState";

function GamepadPage() {
  const { selectedGamepadId, connected } = useGamepadContext();

  return (
    <div className="container mx-auto p-4 max-w-6xl">
      <h1 className="text-2xl font-bold mb-6">Gamepad Controls</h1>

      {/* Always show the GamepadList to allow selection/changing */}
      <GamepadList />

      {/* Only show preview if a gamepad is selected */}
      {selectedGamepadId && (
        <div className="mt-6">
          <GamepadPreview />
        </div>
      )}

      {/* Only show websocket status if a gamepad is selected */}
      <div className="mt-6">
        <WebSocketStatus />
      </div>

      <DebugState />
    </div>
  );
}

export default function GamepadPageWithProvider() {
  return (
    <GamepadProvider>
      <GamepadPage />
    </GamepadProvider>
  );
}
