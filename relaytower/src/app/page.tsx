"use client";
import { GamepadProvider } from "@/contexts/GamepadContext";
import { useGamepadContext } from "@/contexts/GamepadContext";
import GamepadList from "@/components/GamepadList";
import GamepadPreview from "@/components/GamepadPreview";
import WebSocketStatus from "@/components/WebSocketStatus";
import DebugState from "@/components/DebugState";
import CameraFeed from "@/components/CameraFeed";

function GamepadPage() {
  const { selectedGamepadId } = useGamepadContext();

  return (
    <div className="container mx-auto p-4 max-w-6xl">
      <h1 className="text-2xl font-bold mb-6">ByteRacer Control Panel</h1>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="md:col-span-2">
          <CameraFeed />
        </div>

        <div className="space-y-6">
          <GamepadList />
          <WebSocketStatus />
        </div>
      </div>

      {/* Only show preview if a gamepad is selected */}
      {selectedGamepadId && (
        <div className="mt-6">
          <GamepadPreview />
        </div>
      )}

      <div className="mt-6">
        <DebugState />
      </div>
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
