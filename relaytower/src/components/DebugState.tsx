"use client";
import { useGamepadContext } from "@/contexts/GamepadContext";

export default function DebugState() {
  const { availableGamepads, selectedGamepadId, connected, listeningFor } =
    useGamepadContext();

  return (
    <div className="p-4 bg-gray-100 rounded-md my-4 font-mono text-xs">
      <h3 className="font-bold mb-2">DEBUG STATE</h3>
      <div>Available gamepads: {availableGamepads.length}</div>
      <div>Selected ID: {selectedGamepadId || "none"}</div>
      <div>Connected: {connected ? "yes" : "no"}</div>
      <div>Listening for: {listeningFor || "none"}</div>
      {/* <div className="mt-4">
        <button
          className="bg-red-500 text-white px-4 py-2 rounded"
          onClick={() => {
            const mappings = {
              accelerate: { type: "button", index: 0 },
            };
            console.log("Manual test mapping for accelerate -> button 0");
            // Your component could access these directly to test remapping
          }}
        >
          TEST: Map Accelerate to A button
        </button>
      </div> */}
    </div>
  );
}
