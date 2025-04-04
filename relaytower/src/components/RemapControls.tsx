"use client";
import { useGamepadContext } from "@/contexts/GamepadContext";
import { Button } from "./ui/button";
import { ACTIONS } from "@/hooks/useGamepad";
import { useLocalStorage } from "@/hooks/useLocalStorage";

export default function RemapControls() {
  const {
    mappings,
    listenForNextInput,
    listeningFor,
    getInputLabelForMapping,
    remappingType,
    selectedGamepadId,
    resetAllMappings, // Add the resetAllMappings function from context
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

  // Helper function to reset the mappings to default
  function resetMappings() {
    // Use the reset function from the useGamepad hook instead of manually manipulating localStorage
    resetAllMappings();
  }

  // Render function for standard actions (button or axis)
  function renderStandardActionRow(action: (typeof ACTIONS)[0]) {
    const isCurrentlyRemapping = listeningFor === action.key;
    const inputLabel = isCurrentlyRemapping
      ? getRemapPrompt(action)
      : getInputLabel(action.key);

    return (
      <div
        key={action.key}
        className="flex items-center justify-between px-4 py-2.5 border-b border-border last:border-b-0"
      >
        <div className="flex-grow">
          <span className="font-medium">{action.label}:</span>{" "}
          <span
            className={
              isCurrentlyRemapping
                ? "text-primary font-medium animate-pulse"
                : "text-muted-foreground"
            }
          >
            {inputLabel}
          </span>
        </div>
        <Button
          size="sm"
          variant={isCurrentlyRemapping ? "secondary" : "outline"}
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

    // Use the active remapping type from context
    const activeRemappingType = remappingType || "button";

    const inputLabel = isCurrentlyRemapping
      ? getRemapPrompt(action, activeRemappingType)
      : getInputLabel(action.key);

    return (
      <div
        key={action.key}
        className="flex flex-col py-2.5 px-4 border-b border-border last:border-b-0"
      >
        <div className="flex items-center justify-between">
          <div className="flex-grow">
            <span className="font-medium">{action.label}:</span>{" "}
            <span
              className={
                isCurrentlyRemapping
                  ? "text-primary font-medium animate-pulse"
                  : "text-muted-foreground"
              }
            >
              {inputLabel}
              <span className="text-xs ml-1 opacity-70">({currentType})</span>
            </span>
          </div>

          {isCurrentlyRemapping ? (
            <Button
              size="sm"
              variant="secondary"
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
                variant="outline"
                onClick={() => {
                  console.log(`Starting button remap for ${action.key}`);
                  listenForNextInput(action.key, "button");
                }}
              >
                Map Button
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  console.log(`Starting axis remap for ${action.key}`);
                  listenForNextInput(action.key, "axis");
                }}
              >
                Map Axis
              </Button>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex justify-between items-center mb-3">
        <h3 className="text-lg font-semibold">Customize Controls</h3>
        {selectedGamepadId && (
          <Button
            size="sm"
            variant="destructive"
            onClick={resetMappings}
          >
            Reset to Defaults
          </Button>
        )}
      </div>

      {/* Multi-Input Actions (Both) */}
      {bothActions.length > 0 && (
        <div className="mb-4">
          <h4 className="text-md font-medium mb-2 flex items-center">
            Multi-Input Controls
            <span className="text-sm text-muted-foreground ml-2">
              (Button or Axis)
            </span>
          </h4>
          <div className="border rounded-md overflow-hidden">
            {bothActions.map((action) => renderBothTypeActionRow(action))}
          </div>
        </div>
      )}

      {/* Button Actions */}
      {buttonActions.length > 0 && (
        <div className="mb-4">
          <h4 className="text-md font-medium mb-2">Button Controls</h4>
          <div className="border rounded-md overflow-hidden">
            {buttonActions.map((action) => renderStandardActionRow(action))}
          </div>
        </div>
      )}

      {/* Axis Actions */}
      {axisActions.length > 0 && (
        <div className="mb-4">
          <h4 className="text-md font-medium mb-2">Axis Controls</h4>
          <div className="border rounded-md overflow-hidden">
            {axisActions.map((action) => renderStandardActionRow(action))}
          </div>
        </div>
      )}
    </div>
  );
}
