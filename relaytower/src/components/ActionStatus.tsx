"use client";
import { useGamepadContext } from "@/contexts/GamepadContext";
import { ActionInfo } from "@/hooks/useGamepad";
import { Progress } from "./ui/progress";
import AxisConfigSlider from "./AxisConfig";

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
          isActive
            ? "bg-primary/10 border-primary/50"
            : "bg-muted border-muted-foreground/20"
        }`}
      >
        <div className="font-semibold">
          {action.label}
          {action.type === "both" && (
            <span className="text-xs ml-1 text-muted-foreground">
              (Button mode)
            </span>
          )}
        </div>
        <div className="text-sm">{isActive ? "ACTIVE" : "Inactive"}</div>
        <div className="text-xs mt-1 text-muted-foreground">
          Mapped to: {inputLabel}
        </div>
      </div>
    );
  }

  // For axis type actions (or "both" mapped to axes), show value and gradient
  if (effectiveType === "axis") {
    // Calculate position as percentage (0-100)
    const percentage = (((axisValue || 0) + 1) / 2) * 100;

    return (
      <div className="p-3 border rounded-md">
        <div className="font-semibold">
          {action.label}
          {action.type === "both" && (
            <span className="text-xs ml-1 text-muted-foreground">
              (Axis mode)
            </span>
          )}
        </div>
        <div className="text-sm">Value: {axisValue?.toFixed(2) || 0}</div>

        <div className="relative my-2">
          <Progress className="h-4 bg-secondary/50" value={percentage} />

          {/* Center marker */}
          <div className="absolute inset-y-0 w-0.5 bg-muted-foreground/50 left-1/2 z-10"></div>

          {/* Value indicator marker */}
          <div
            className="absolute top-0 bottom-0 w-1 bg-foreground z-20"
            style={{
              left: `calc(${percentage}%)`,
              transform: "translateX(-50%)",
            }}
          ></div>
        </div>

        <div className="text-xs text-muted-foreground">
          Mapped to: {inputLabel}
        </div>

        {/* Add the axis configuration slider */}
        <AxisConfigSlider action={action} />
      </div>
    );
  }
}
