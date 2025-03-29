"use client";
import { useGamepadContext } from "@/contexts/GamepadContext";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { useEffect, useRef, useCallback } from "react";
import { ActionKey, ActionInfo } from "@/hooks/useGamepad";

// Type for gamepad state values
type GamepadStateValue = boolean | string | number;

export default function GamepadInputHandler() {
  const {
    isActionActive,
    getAxisValueForAction,
    selectedGamepadId,
    mappings,
    ACTION_GROUPS,
    ACTIONS,
  } = useGamepadContext();

  const { status, sendGamepadState } = useWebSocket();

  // Store function references in refs to avoid dependency issues
  const functionsRef = useRef({
    isActionActive,
    getAxisValueForAction,
    ACTION_GROUPS,
    ACTIONS,
  });

  // Keep refs in sync with the latest functions
  useEffect(() => {
    functionsRef.current = {
      isActionActive,
      getAxisValueForAction,
      ACTION_GROUPS,
      ACTIONS,
    };
  }, [isActionActive, getAxisValueForAction, ACTION_GROUPS, ACTIONS]);

  // Compute the current gamepad state from inputs
  const computeGamepadState = useCallback(() => {
    const { isActionActive, getAxisValueForAction, ACTION_GROUPS, ACTIONS } =
      functionsRef.current;

    const gamepadState: Record<string, GamepadStateValue> = {};
    const processedActions = new Set<ActionKey>(); // Track which actions we've already processed

    // Process each action group to create a combined value
    ACTION_GROUPS.forEach((group) => {
      // Only process groups with exactly 2 opposing actions (like forward/backward)
      if (group.actions.length === 2) {
        const [action1, action2] = group.actions;

        // Get values for both actions in the group
        const value1 = getActionValue(action1);
        const value2 = getActionValue(action2);

        // Combine the values (positive - negative)
        gamepadState[group.key] = (value1 - value2).toFixed(2);

        // Mark these actions as processed
        processedActions.add(action1);
        processedActions.add(action2);
      } else {
        // For groups with different number of actions, process individually
        group.actions.forEach((action) => {
          processAction(action);
          processedActions.add(action);
        });
      }
    });

    // Now process any remaining actions that weren't part of a group
    ACTIONS.forEach((actionInfo: ActionInfo) => {
      if (!processedActions.has(actionInfo.key)) {
        processAction(actionInfo.key);
      }
    });

    return gamepadState;

    // Function to process an individual action and add it to gamepadState
    function processAction(action: ActionKey) {
      const mapping = mappings[action];
      if (!mapping || mapping.index === -1) return;

      const actionInfo = ACTIONS.find((a: ActionInfo) => a.key === action);
      if (!actionInfo) return;

      // Handle actions based on their type
      if (
        actionInfo.type === "button" ||
        (actionInfo.type === "both" && mapping.type === "button")
      ) {
        // For button actions (or "both" mapped to button)
        gamepadState[action] = isActionActive(action);
      } else if (
        actionInfo.type === "axis" ||
        (actionInfo.type === "both" && mapping.type === "axis")
      ) {
        // For axis actions (or "both" mapped to axis)
        const value = getAxisValueForAction(action);
        if (value !== undefined) {
          gamepadState[action] = value.toFixed(2);
        }
      }
    }

    // Helper function to get normalized value for an action
    function getActionValue(action: ActionKey): number {
      const mapping = mappings[action];

      if (!mapping || mapping.index === -1) {
        return 0;
      }

      if (mapping.type === "button") {
        return isActionActive(action) ? 1 : 0;
      }

      if (mapping.type === "axis") {
        return getAxisValueForAction(action) ?? 0;
      }

      return 0;
    }
  }, [mappings]);

  // Send gamepad state periodically
  useEffect(() => {
    // Only send data if connected to WebSocket AND have a selected gamepad
    if (status !== "connected" || !selectedGamepadId) return;

    const interval = setInterval(() => {
      // Get the comprehensive gamepad state
      const gamepadState = computeGamepadState();
      
      // Send the state via WebSocket
      sendGamepadState(gamepadState);
    }, 50); // Send updates at 20 Hz

    return () => clearInterval(interval);
  }, [status, selectedGamepadId, computeGamepadState, sendGamepadState]);

  // This component doesn't render anything visible
  return null;
}