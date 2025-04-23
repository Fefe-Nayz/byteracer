"use client";
import { useGamepadContext } from "@/contexts/GamepadContext";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { useEffect, useRef, useCallback, useState } from "react";
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

  const { status, sendGamepadState, playSound } = useWebSocket();
  const [selectedSound, setSelectedSound] = useState<string>("fart");
  const [lastUseState, setLastUseState] = useState<boolean>(false);

  // Track whether the "use" button was previously pressed
  const useButtonRef = useRef<boolean>(false);
  
  // Listen for sound selection updates from SoundEffects component
  useEffect(() => {
    const handleSoundUpdate = (event: CustomEvent) => {
      setSelectedSound(event.detail.selectedSound);
    };
    
    window.addEventListener("sound:selected-update", handleSoundUpdate as EventListener);
    
    return () => {
      window.removeEventListener("sound:selected-update", handleSoundUpdate as EventListener);
    };
  }, []);

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

    // Debug the current raw gamepad state
    const pads = navigator.getGamepads ? navigator.getGamepads() : [];
    const activePad = Array.from(pads).find(
      (g) => g && g.id === selectedGamepadId
    );
    
    // Create a basic gamepad state that will always have these values
    // This ensures we're always sending something, even if no buttons are pressed
    const gamepadState: Record<string, GamepadStateValue> = {
      timestamp: Date.now(),
      connected: !!activePad,
      // Default values for the main control axes
      speed: "0.00",
      turn: "0.00"
    };
    
    if (activePad) {
      // Process raw gamepad data
      const axes = Array.from(activePad.axes);
      const buttons = Array.from(activePad.buttons).map(b => b.pressed);
      
      // Add raw values to state for debugging
      gamepadState._raw_axes = JSON.stringify(axes);
      gamepadState._raw_buttons = JSON.stringify(buttons);
      
      // Process through the action groups and mappings...
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
    } else {
      // console.log("No active gamepad found despite selectedGamepadId being set:", selectedGamepadId);
    }

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
  }, [mappings, selectedGamepadId]);

  // Check for "use" button press and trigger sound playback
  useEffect(() => {
    if (status !== "connected" || !selectedGamepadId) return;
    
    // Check if the "use" button state changed from not pressed to pressed
    const useButtonActive = isActionActive("use");
    
    if (useButtonActive && !useButtonRef.current) {
      // Button just pressed, play the selected sound
      playSound(selectedSound);
    }
    
    // Update the ref with current state for next comparison
    useButtonRef.current = useButtonActive;
    
  }, [isActionActive, selectedGamepadId, selectedSound, status, playSound]);

  // Send gamepad state periodically
  useEffect(() => {
    // Only send data if connected to WebSocket AND have a selected gamepad
    if (status !== "connected" || !selectedGamepadId) {
      // console.log(`Not sending gamepad data: WebSocket status=${status}, selectedGamepadId=${selectedGamepadId}`);
      return;
    }

    
    // Force an immediate send of gamepad state
    const sendGamepadUpdate = () => {
      // Get the comprehensive gamepad state
      const gamepadState = computeGamepadState();
      
      // Log the gamepad state being sent (uncomment for debugging)
      // console.log("Sending gamepad state:", gamepadState);
      
      // Check if the "use" button state changed
      const currentUseState = isActionActive("use");
      if (currentUseState !== lastUseState) {
        setLastUseState(currentUseState);
      }
      
      // Always send the state even if it appears empty
      // This ensures continuous updates are sent to the robot
      sendGamepadState(gamepadState);
    };
    
    // Send initial state immediately
    sendGamepadUpdate();
    
    // Then set up interval
    const interval = setInterval(sendGamepadUpdate, 50); // Send updates at 20 Hz

    return () => {
      clearInterval(interval);
    };
  }, [status, selectedGamepadId, computeGamepadState, sendGamepadState, isActionActive, lastUseState]);

  // This component doesn't render anything visible
  return null;
}