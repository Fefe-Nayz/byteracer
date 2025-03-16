"use client";
import { useGamepadContext } from "@/contexts/GamepadContext";
import { ActionInfo, ActionKey } from "@/hooks/useGamepad";

export default function ActionStatus({ action }: { action: ActionInfo }) {
  const {
    isActionActive,
    getAxisValueForAction,
    mappings,
    getInputLabelForMapping,
  } = useGamepadContext();

  const isActive = isActionActive(action.key);
  const mapping = mappings[action.key];
  const inputLabel = mapping ? getInputLabelForMapping(mapping) : "Not mapped";

  // Determine if this is a "both" type action mapped as a button or axis
  const currentMappingType = mapping?.type || "button";

  // For "both" type actions, use the current mapping type to determine display
  const effectiveType =
    action.type === "both" ? currentMappingType : action.type;

  // Get axis value if this is an axis-mapped action
  const axisValue =
    effectiveType === "axis"
      ? getAxisValueForAction(action.key) ?? 0
      : undefined;

  // For button type actions (or "both" mapped to buttons), show active/inactive state
  if (effectiveType === "button") {
    return (
      <div
        className={`p-3 border rounded-md ${
          isActive ? "bg-green-200" : "bg-red-100"
        }`}
      >
        <div className="font-semibold">
          {action.label}
          {action.type === "both" && (
            <span className="text-xs ml-1">(Button mode)</span>
          )}
        </div>
        <div className="text-sm">{isActive ? "ACTIVE" : "Inactive"}</div>
        <div className="text-xs mt-1">Mapped to: {inputLabel}</div>
      </div>
    );
  }

  // For axis type actions (or "both" mapped to axes), show value and gradient
  const axisStyle = {
    background: `linear-gradient(to right, #f87171 ${
      50 - (axisValue || 0) * 50
    }%, #86efac ${50 - (axisValue || 0) * 50}%)`,
  };

  return (
    <div className="p-3 border rounded-md">
      <div className="font-semibold">
        {action.label}
        {action.type === "both" && (
          <span className="text-xs ml-1">(Axis mode)</span>
        )}
      </div>
      <div className="text-sm">Value: {axisValue?.toFixed(2) || 0}</div>

      <div
        className="relative h-4 mt-1 bg-gray-200 rounded-full overflow-hidden"
        style={axisStyle}
      >
        {/* Center indicator */}
        <div className="absolute h-full w-0.5 bg-black left-1/2 transform -translate-x-1/2 opacity-50"></div>

        {/* Value indicator */}
        <div
          className="absolute h-full w-1.5 bg-black"
          style={{
            left: `${50 + (axisValue || 0) * 50}%`,
            transform: "translateX(-50%)",
          }}
        ></div>
      </div>

      <div className="text-xs mt-1">Mapped to: {inputLabel}</div>
    </div>
  );
}
