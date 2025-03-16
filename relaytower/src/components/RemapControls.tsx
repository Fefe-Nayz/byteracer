"use client";
import { useGamepadContext } from "@/contexts/GamepadContext";
import { Button } from "./ui/button";
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
  const bothActions = ACTIONS.filter((action) => action.type === "both");

  // Helper function to get the mapped input label
  function getInputLabel(key: string) {
    const map = mappings[key as keyof typeof mappings];
    if (!map || map.index === -1) return "Not mapped";
    return getInputLabelForMapping(map);
  }

  // Helper to create a remapping message based on action type
  function getRemapPrompt(
    action: (typeof ACTIONS)[0],
    preferredType?: "button" | "axis"
  ) {
    if (preferredType === "button" || action.type === "button")
      return "Press any button...";
    if (preferredType === "axis" || action.type === "axis")
      return "Move any axis...";
    return "Waiting for input...";
  }

  // Render function for standard actions (button or axis)
  function renderStandardActionRow(action: (typeof ACTIONS)[0]) {
    const isCurrentlyRemapping = listeningFor === action.key;
    const inputLabel = isCurrentlyRemapping
      ? getRemapPrompt(action)
      : getInputLabel(action.key);

    return (
      <div key={action.key} className="flex items-center justify-between">
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
  }

  // Special render function for "both" type actions
  function renderBothTypeActionRow(action: (typeof ACTIONS)[0]) {
    const isCurrentlyRemapping = listeningFor === action.key;

    // Get current mapping info
    const map = mappings[action.key];
    const currentType = map ? map.type : "button";
    const inputLabel = isCurrentlyRemapping
      ? getRemapPrompt(action, map?.type)
      : getInputLabel(action.key);

    return (
      <div key={action.key} className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <div className="flex-grow">
            <span className="font-medium">{action.label}:</span>{" "}
            <span className="text-blue-600">
              {inputLabel}
              <span className="text-xs text-gray-500 ml-1">
                ({currentType})
              </span>
            </span>
          </div>

          {isCurrentlyRemapping ? (
            <Button
              size="sm"
              onClick={() => {
                console.log(`Canceling remap for ${action.key}`);
                listenForNextInput(null);
              }}
            >
              Cancel
            </Button>
          ) : (
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={() => {
                  console.log(`Starting button remap for ${action.key}`);
                  listenForNextInput(action.key, "button");
                }}
              >
                Remap a Button
              </Button>
              <Button
                size="sm"
                onClick={() => {
                  console.log(`Starting axis remap for ${action.key}`);
                  listenForNextInput(action.key, "axis");
                }}
              >
                Remap an Axis
              </Button>
            </div>
          )}
        </div>
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
          <div className="space-y-3">
            {bothActions.map((action) => renderBothTypeActionRow(action))}
          </div>
        </div>
      )}

      {/* Button Actions */}
      {buttonActions.length > 0 && (
        <div className="mb-4">
          <h4 className="text-md font-medium mb-2">Button Controls</h4>
          <div className="space-y-2">
            {buttonActions.map((action) => renderStandardActionRow(action))}
          </div>
        </div>
      )}

      {/* Axis Actions */}
      {axisActions.length > 0 && (
        <div className="mb-4">
          <h4 className="text-md font-medium mb-2">Axis Controls</h4>
          <div className="space-y-2">
            {axisActions.map((action) => renderStandardActionRow(action))}
          </div>
        </div>
      )}
    </div>
  );
}
