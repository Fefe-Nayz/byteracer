"use client";
import { useGamepadContext } from "@/contexts/GamepadContext";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { ACTIONS } from "@/hooks/useGamepad";

export default function RemapControls() {
  const {
    mappings,
    listenForNextInput,
    listeningFor,
    getInputLabelForMapping,
  } = useGamepadContext();

  // Filter actions by type
  const buttonActions = ACTIONS.filter((action) => action.type === "button");
  const axisActions = ACTIONS.filter((action) => action.type === "axis");

  // Helper function to get the mapped input label
  function getInputLabel(key: string) {
    const map = mappings[key as keyof typeof mappings];
    if (!map || map.index === -1) return "Not mapped";
    return getInputLabelForMapping(map);
  }

  return (
    <div>
      <h3 className="text-lg font-semibold mb-3">Customize Controls</h3>

      {/* Button Actions */}
      <div className="mb-4">
        <h4 className="text-md font-medium mb-2">Button Controls</h4>
        <div className="space-y-2">
          {buttonActions.map((action) => {
            const isCurrentlyRemapping = listeningFor === action.key;
            const inputLabel = isCurrentlyRemapping
              ? "Press any button..."
              : getInputLabel(action.key);

            return (
              <div
                key={action.key}
                className="flex items-center justify-between"
              >
                <div className="flex-grow">
                  <span className="font-medium">{action.label}:</span>{" "}
                  <span className="text-blue-600">{inputLabel}</span>
                </div>
                <Button
                  size="sm"
                  onClick={() => {
                    if (isCurrentlyRemapping) {
                      console.log(`Canceling remap for ${action.key}`);
                      listenForNextInput(null);
                    } else {
                      console.log(`Starting remap for ${action.key}`);
                      listenForNextInput(action.key);
                    }
                  }}
                >
                  {isCurrentlyRemapping ? "Cancel" : "Remap"}
                </Button>
              </div>
            );
          })}
        </div>
      </div>

      {/* Axis Actions */}
      <div>
        <h4 className="text-md font-medium mb-2">Axis Controls</h4>
        <div className="space-y-2">
          {axisActions.map((action) => {
            const isCurrentlyRemapping = listeningFor === action.key;
            const inputLabel = isCurrentlyRemapping
              ? "Move any axis..."
              : getInputLabel(action.key);

            return (
              <div
                key={action.key}
                className="flex items-center justify-between"
              >
                <div className="flex-grow">
                  <span className="font-medium">{action.label}:</span>{" "}
                  <span className="text-blue-600">{inputLabel}</span>
                </div>
                <Button
                  size="sm"
                  onClick={() => {
                    if (isCurrentlyRemapping) {
                      console.log(`Canceling remap for ${action.key}`);
                      listenForNextInput(null);
                    } else {
                      console.log(`Starting remap for ${action.key}`);
                      listenForNextInput(action.key);
                    }
                  }}
                >
                  {isCurrentlyRemapping ? "Cancel" : "Remap"}
                </Button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
