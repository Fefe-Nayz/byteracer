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

  // Filter actions by type - now separating "both" into its own category
  const buttonActions = ACTIONS.filter((action) => action.type === "button");
  const axisActions = ACTIONS.filter((action) => action.type === "axis");
  const bothActions = ACTIONS.filter((action) => action.type === "both");

  // Helper function to get the mapped input label
  function getInputLabel(key: string) {
    const map = mappings[key as keyof typeof mappings];
    if (!map || map.index === -1) return "Not mapped";
    return getInputLabelForMapping(map);
  }

  // Helper to create a remapping message based on action type
  function getRemapPrompt(action: (typeof ACTIONS)[0]) {
    if (action.type === "button") return "Press any button...";
    if (action.type === "axis") return "Move any axis...";
    if (action.type === "both") return "Press any button or move any axis...";
    return "Waiting for input...";
  }

  // Shared render function for action rows to avoid code duplication
  function renderActionRow(action: (typeof ACTIONS)[0]) {
    const isCurrentlyRemapping = listeningFor === action.key;
    const inputLabel = isCurrentlyRemapping
      ? getRemapPrompt(action)
      : getInputLabel(action.key);

    // Show which current type is mapped for "both" actions
    const isBothType = action.type === "both";
    const currentType =
      isBothType && mappings[action.key]
        ? `(${mappings[action.key].type})`
        : "";

    return (
      <div key={action.key} className="flex items-center justify-between">
        <div className="flex-grow">
          <span className="font-medium">
            {action.label}
            {isBothType ? " " + currentType : ""}:
          </span>{" "}
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
  }

  return (
    <div>
      <h3 className="text-lg font-semibold mb-3">Customize Controls</h3>

      {/* Multi-Input Actions (Both) */}
      {bothActions.length > 0 && (
        <div className="mb-4">
          <h4 className="text-md font-medium mb-2">
            Multi-Input Controls
            <span className="text-sm text-gray-500 ml-2">(Button or Axis)</span>
          </h4>
          <div className="space-y-2">
            {bothActions.map((action) => renderActionRow(action))}
          </div>
        </div>
      )}

      {/* Button Actions */}
      {buttonActions.length > 0 && (
        <div className="mb-4">
          <h4 className="text-md font-medium mb-2">Button Controls</h4>
          <div className="space-y-2">
            {buttonActions.map((action) => renderActionRow(action))}
          </div>
        </div>
      )}

      {/* Axis Actions */}
      {axisActions.length > 0 && (
        <div className="mb-4">
          <h4 className="text-md font-medium mb-2">Axis Controls</h4>
          <div className="space-y-2">
            {axisActions.map((action) => renderActionRow(action))}
          </div>
        </div>
      )}
    </div>
  );
}
