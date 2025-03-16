"use client";
import { useEffect, useState, useRef } from "react";
import { useLocalStorage } from "./useLocalStorage";

// Types
export type GamepadButtonInput = {
  id: string;
  type: "button";
  index: number;
  label: string;
};

export type GamepadAxisInput = {
  id: string;
  type: "axis";
  index: number;
  label: string;
};

export type GamepadInput = GamepadButtonInput | GamepadAxisInput;

export type ActionKey = "accelerate" | "brake" | "turn" | "turnCameraX" | "turnCameraY";

export interface ActionInfo {
  key: ActionKey;
  label: string;
  type: "button" | "axis" | "both"
}

export const ACTIONS: ActionInfo[] = [
  { key: "accelerate", label: "Accélérer", type: "both" },
  { key: "brake", label: "Freiner", type: "both" },
  { key: "turn", label: "Tourner", type: "axis" },
  { key: "turnCameraX", label: "Tourner la caméra horizontalement", type: "axis" },
  { key: "turnCameraY", label: "Tourner la caméra verticalement", type: "axis" },
];

type Mapping = Record<ActionKey, { type: "button" | "axis"; index: number }>;

type GamepadState = {
  connected: boolean;
  pressedInputs: Set<string>;
  axisValues: number[];
  _lastUpdate?: number;
};

type StoredMappings = {
  [gamepadId: string]: Mapping;
};

export function useGamepad() {
  const [availableGamepads, setAvailableGamepads] = useState<Gamepad[]>([]);
  const [selectedGamepadId, setSelectedGamepadId] = useState<string | null>(null);
  const [gamepadState, setGamepadState] = useState<GamepadState>({
    connected: false,
    pressedInputs: new Set(),
    axisValues: [0, 0, 0, 0],
  });
  
  // Dynamic inputs for the current gamepad
  const [gamepadInputs, setGamepadInputs] = useState<{
    buttons: GamepadButtonInput[];
    axes: GamepadAxisInput[];
  }>({
    buttons: [],
    axes: [],
  });
  
  // Store mappings per gamepad ID
  const [storedMappings, setStoredMappings] = useLocalStorage<StoredMappings>(
    "gamepad-mappings",
    {}
  );
  
  // Current mappings for the selected gamepad
  const [mappings, setMappings] = useState<Mapping>({
    accelerate: { type: "button", index: 0 },
    brake: { type: "button", index: 1 },
    turn: { type: "axis", index: 0 },
    turnCameraX: { type: "axis", index: 2 },
    turnCameraY: { type: "axis", index: 3 },
  });
  
  const [listeningFor, setListeningFor] = useState<ActionKey | null>(null);

  // Track if we're in the middle of loading from storage
  const isLoadingFromStorage = useRef(false);
  const isInitialLoad = useRef(true);

  // First, make sure remappingRef's type includes initialAxisValues
  const remappingRef = useRef<{
    active: boolean;
    action: ActionKey | null;
    actionType: "button" | "axis" | "both" | null;
    initialAxisValues?: number[];
  }>({
    active: false,
    action: null,
    actionType: null,
    initialAxisValues: []
  });

  // Update mappings when gamepad changes - load from storage
  useEffect(() => {
    if (!selectedGamepadId) return;
    
    // Only load from storage if we have a gamepad selected
    if (selectedGamepadId && storedMappings[selectedGamepadId]) {
      // Prevent saving during loading
      isLoadingFromStorage.current = true;
      
      // Load saved mappings
      setMappings(storedMappings[selectedGamepadId]);
      
      // Re-enable saving after this render cycle
      setTimeout(() => {
        isLoadingFromStorage.current = false;
      }, 0);
    } else if (selectedGamepadId) {
      // Default mappings for this gamepad
      setMappings({
        accelerate: { type: "button", index: 0 },
        brake: { type: "button", index: 1 },
        turn: { type: "axis", index: 0 },
        turnCameraX: { type: "axis", index: 2 },
        turnCameraY: { type: "axis", index: 3 },
      });
    }
    
    // Only depends on selectedGamepadId and storedMappings
  }, [selectedGamepadId, storedMappings]);

  // Save mappings when they change due to user actions
  useEffect(() => {
    // Skip saving on the initial load or when loading from storage
    if (isInitialLoad.current) {
      isInitialLoad.current = false;
      return;
    }
    
    if (isLoadingFromStorage.current) {
      return;
    }
    
    // Only save if we have a gamepad selected
    if (selectedGamepadId) {
      setStoredMappings((prev) => {
        // Only update if the mappings actually changed
        if (JSON.stringify(prev[selectedGamepadId]) === JSON.stringify(mappings)) {
          return prev; // No change, return the same object
        }
        
        // Update with the new mappings
        return {
          ...prev,
          [selectedGamepadId]: mappings,
        };
      });
    }
  }, [mappings, selectedGamepadId, setStoredMappings]);

  // Select a gamepad
  function selectGamepad(gamepad: Gamepad | null) {
    setSelectedGamepadId(gamepad?.id || null);
    
    // Generate dynamic inputs for this gamepad
    if (gamepad) {
      // Create button inputs
      const buttons: GamepadButtonInput[] = [];
      for (let i = 0; i < gamepad.buttons.length; i++) {
        // Standard mapping labels or generic ones
        let label = "Button " + i;
        if (gamepad.mapping === "standard") {
          // Map standard gamepad buttons to labels
          switch (i) {
            case 0: label = "A"; break;
            case 1: label = "B"; break;
            case 2: label = "X"; break;
            case 3: label = "Y"; break;
            case 4: label = "LB"; break;
            case 5: label = "RB"; break;
            case 6: label = "LT"; break;
            case 7: label = "RT"; break;
            case 8: label = "Select"; break;
            case 9: label = "Start"; break;
            case 10: label = "L3"; break; // Left stick button
            case 11: label = "R3"; break; // Right stick button
            case 12: label = "D-Pad Up"; break;
            case 13: label = "D-Pad Down"; break;
            case 14: label = "D-Pad Left"; break;
            case 15: label = "D-Pad Right"; break;
          }
        }
        
        buttons.push({
          id: `button-${i}`,
          type: "button",
          index: i,
          label
        });
      }
      
      // Create axis inputs
      const axes: GamepadAxisInput[] = [];
      for (let i = 0; i < gamepad.axes.length; i++) {
        let label = "Axis " + i;
        // Standard mapping labels
        if (gamepad.mapping === "standard") {
          switch (i) {
            case 0: label = "Left Stick X"; break;
            case 1: label = "Left Stick Y"; break;
            case 2: label = "Right Stick X"; break;
            case 3: label = "Right Stick Y"; break;
          }
        }
        
        axes.push({
          id: `axis-${i}`,
          type: "axis",
          index: i,
          label
        });
      }
      
      setGamepadInputs({ buttons, axes });
    } else {
      setGamepadInputs({ buttons: [], axes: [] });
    }
  }

  function updateAvailableGamepads() {
    const pads = navigator.getGamepads ? navigator.getGamepads() : [];
    const gamepads: Gamepad[] = [];
    
    for (let i = 0; i < pads.length; i++) {
      if (pads[i]) {
        gamepads.push(pads[i]!);
      }
    }
    
    setAvailableGamepads(gamepads);
  }

  // Start or cancel remapping
  function listenForNextInput(action: ActionKey | null, preferredType?: "button" | "axis") {
    if (action === null) {
      console.log("Cancelling remap operation");
      setListeningFor(null);
      remappingRef.current = {
        active: false,
        action: null,
        actionType: null
      };
      return;
    }
    
    // Find action type
    const actionInfo = ACTIONS.find(a => a.key === action);
    
    // Use preferred type if specified, otherwise use action's default type
    const actionType = preferredType || actionInfo?.type || "button";
    
    console.log(`Now listening for ${actionType} input for action ${action}`);
    
    // Store initial axis values for proper detection
    const pads = navigator.getGamepads ? navigator.getGamepads() : [];
    const activePad = Array.from(pads).find(g => g && g.id === selectedGamepadId);
    const initialAxisValues = activePad ? [...activePad.axes] : [];
    
    setListeningFor(action);
    remappingRef.current = {
      active: true,
      action: action,
      actionType: actionType,
      initialAxisValues: initialAxisValues
    };
  }

  // Check if an action is active
  function isActionActive(action: ActionKey): boolean {
    if (!gamepadState.connected) return false;
    const map = mappings[action];
    if (!map || map.index === -1) return false; // Check for -1 (unmapped)

    // Find the action info to check if it's "both" type
    const actionInfo = ACTIONS.find(a => a.key === action);
    
    if (map.type === "button") {
      const id = `button-${map.index}`;
      return gamepadState.pressedInputs.has(id);
    } else if (map.type === "axis") {
      // For axis
      const val = gamepadState.axisValues[map.index] ?? 0;
      
      // For turn actions, use different thresholds
      if (action === "turn") {
        return Math.abs(val) > 0.2; 
      } else if (action === "turnCameraX" || action === "turnCameraY") {
        return Math.abs(val) > 0.2;
      }

      return Math.abs(val) > 0.2;
    }
    
    // Should never reach here, but better safe
    return false;
  }
  
  // Get the axis value for an action
  function getAxisValueForAction(action: ActionKey): number | undefined {
    if (!gamepadState.connected) return 0;
    const map = mappings[action];
    if (!map || map.type !== "axis") return undefined;
    
    return gamepadState.axisValues[map.index] ?? 0;
  }

  // Find which action is mapped to a specific input
  function getActionForInput(type: "button" | "axis", index: number): ActionKey | null {
    for (const [action, cfg] of Object.entries(mappings) as [ActionKey, { type: string; index: number }][]) {
      if (cfg.type === type && cfg.index === index) {
        return action as ActionKey;
      }
    }
    return null;
  }

  // Find if any action is using this input
  function findActionUsingInput(type: "button" | "axis", index: number, currentMappings?: Mapping): ActionKey | null {
    // Use provided mappings or fall back to the current state mappings
    const mappingsToCheck = currentMappings || mappings;
    
    for (const [action, cfg] of Object.entries(mappingsToCheck) as [ActionKey, { type: string; index: number }][]) {
      if (cfg.type === type && cfg.index === index) {
        return action as ActionKey;
      }
    }
    return null;
  }
  
  // Get label for input mapping
  function getInputLabelForMapping(mapping: { type: string; index: number }): string {
    if (mapping.type === "button") {
      const found = gamepadInputs.buttons.find(btn => btn.index === mapping.index);
      return found ? found.label : "Unknown Button";
    } else if (mapping.type === "axis") {
      const found = gamepadInputs.axes.find(axis => axis.index === mapping.index);
      return found ? found.label : "Unknown Axis";
    }
    return "Unknown";
  }

  /** Polling function, called periodically. */
  function updateGamepadState() {
    // Debug output every few seconds when in listening mode
    console.log("updateGamepadState running - selectedID:", selectedGamepadId, 
              "listening:", listeningFor, 
              "connected:", gamepadState.connected);

    const now = Date.now();
    if (listeningFor && (now % 1000 < 50)) {
      console.log("Still listening for:", listeningFor);
      console.log("Current gamepad state:", 
        gamepadState.connected ? "connected" : "disconnected",
        "Buttons pressed:", Array.from(gamepadState.pressedInputs));
    }

    updateAvailableGamepads();
    
    if (!selectedGamepadId) {
      // Early return
      console.log("No gamepad ID selected, skipping remap check");
      if (gamepadState.connected) {
        setGamepadState({
          connected: false,
          pressedInputs: new Set(),
          axisValues: [0, 0, 0, 0],
        });
      }
      return;
    }
    
    const pads = navigator.getGamepads ? navigator.getGamepads() : [];
    const activePad = Array.from(pads).find(g => g && g.id === selectedGamepadId);

    if (!activePad) {
      console.log("Selected gamepad not found in navigator.getGamepads()");
      if (gamepadState.connected) {
        setGamepadState({
          connected: false,
          pressedInputs: new Set(),
          axisValues: [0, 0, 0, 0],
        });
      }
      return;
    }
    
    // Build pressed buttons set
    const newPressed = new Set<string>();
    for (let i = 0; i < activePad.buttons.length; i++) {
      if (activePad.buttons[i].pressed) {
        newPressed.add(`button-${i}`);
      }
    }
    
    // Get axis values
    const newAxes = [...activePad.axes];
    
    // Create new state
    const newState: GamepadState = {
      connected: true,
      pressedInputs: newPressed,
      axisValues: newAxes,
    };
    
    // If listening for remapping
    if (remappingRef.current.active && remappingRef.current.action) {
      const action = remappingRef.current.action;
      const actionType = remappingRef.current.actionType;
      
      console.log(`Checking for ${actionType} input for action ${action}`);
      
      // For button-type actions or "both" type
      if (actionType === "button" || actionType === "both") {
        // Check each button directly
        for (let i = 0; i < activePad.buttons.length; i++) {
          const buttonState = activePad.buttons[i];
          
          // Check if pressed or value > 0.5 (for analog buttons/triggers)
          if (buttonState.pressed || buttonState.value > 0.5) {
            console.log(`Button ${i} detected for ${action} (pressed=${buttonState.pressed}, value=${buttonState.value})`);
            
            // Make sure this is a new button press - wasn't already pressed
            const wasPressed = gamepadState.pressedInputs.has(`button-${i}`);
            if (wasPressed) {
              // Skip if it was already pressed in previous frame - debounce
              continue;
            }
            
            // Map to button type
            remapToButton(action, i);
            return; // Exit after successful remap
          }
        }
      }
      
      // For axis-type actions or "both" type
      if (actionType === "axis" || actionType === "both") {
        for (let i = 0; i < activePad.axes.length; i++) {
          const currentValue = activePad.axes[i];
          const initialValue = remappingRef.current.initialAxisValues?.[i] || 0;
          
          // Calculate movement delta
          const change = Math.abs(currentValue - initialValue);
          
          // Only detect significant movement
          if (change > 0.7) {
            console.log(`Axis ${i} moved from ${initialValue} to ${currentValue} (change: ${change}) for ${action}`);
            
            // Map to axis type
            remapToAxis(action, i);
            return; // Exit after successful remap
          }
        }
      }
    }
    
    // Log the buttons state in each poll during remapping
    if (remappingRef.current.active) {
      let activeButtons = [];
      for (let i = 0; i < activePad.buttons.length; i++) {
        if (activePad.buttons[i].pressed || activePad.buttons[i].value > 0.5) {
          activeButtons.push(`Button ${i}: ${activePad.buttons[i].value.toFixed(2)}`);
        }
      }
      if (activeButtons.length > 0) {
        console.log("Active buttons:", activeButtons.join(", "));
      }
    }
    
    // Update state if changed
    const prevJSON = JSON.stringify({
      connected: gamepadState.connected,
      pressedInputs: Array.from(gamepadState.pressedInputs),
      axisValues: gamepadState.axisValues
    });
    
    const newJSON = JSON.stringify({
      connected: newState.connected,
      pressedInputs: Array.from(newState.pressedInputs),
      axisValues: newState.axisValues
    });
    
    if (prevJSON !== newJSON) {
      setGamepadState(newState);
    }
  }
  
  function remapToButton(action: ActionKey, buttonIndex: number) {
    // Update mapping, handling any conflicts within the setMappings callback
    setMappings(prev => {
      // Check conflicts using the current state from the callback
      const conflictingAction = findActionUsingInput("button", buttonIndex, prev);
      
      const newMappings = { ...prev };
      
      // If button already assigned to a different action, clear that assignment
      if (conflictingAction && conflictingAction !== action) {
        console.log(`Removing button ${buttonIndex} from ${conflictingAction} (conflict resolution)`);
        newMappings[conflictingAction] = { type: "button", index: -1 }; // -1 means unassigned
      }
      
      // Assign the button to the current action
      newMappings[action] = { type: "button", index: buttonIndex };
      return newMappings;
    });
    
    // Clear remapping mode
    remappingRef.current = {
      active: false,
      action: null,
      actionType: null
    };
    setListeningFor(null);
    
    console.log("Remapping complete with conflict resolution (button)");
  }
  
  function remapToAxis(action: ActionKey, axisIndex: number) {
    // Update mapping, handling any conflicts within the setMappings callback
    setMappings(prev => {
      // Check conflicts using the current state from the callback
      const conflictingAction = findActionUsingInput("axis", axisIndex, prev);
      
      const newMappings = { ...prev };
      
      // If axis already assigned to a different action, clear that assignment
      if (conflictingAction && conflictingAction !== action) {
        console.log(`Removing axis ${axisIndex} from ${conflictingAction} (conflict resolution)`);
        newMappings[conflictingAction] = { type: "axis", index: -1 }; 
      }
      
      // Assign the axis to the current action
      newMappings[action] = { type: "axis", index: axisIndex };
      return newMappings;
    });
    
    // Clear remapping mode
    remappingRef.current = {
      active: false,
      action: null,
      actionType: null
    };
    setListeningFor(null);
    
    console.log("Remapping complete with conflict resolution (axis)");
  }
  
  // Set up event listeners and polling
  useEffect(() => {
    function onConnect(e: GamepadEvent) {
      console.log("Gamepad connected:", e.gamepad.id);
      updateAvailableGamepads();
    }
    
    function onDisconnect(e: GamepadEvent) {
      console.log("Gamepad disconnected:", e.gamepad.id);
      updateAvailableGamepads();
      
      if (selectedGamepadId === e.gamepad.id) {
        setSelectedGamepadId(null);
      }
    }
    
    window.addEventListener("gamepadconnected", onConnect);
    window.addEventListener("gamepaddisconnected", onDisconnect);
    
    // Initial update
    updateAvailableGamepads();
    
    // Update gamepad list periodically
    const gamepadListInterval = setInterval(updateAvailableGamepads, 2000);
    
    // Update gamepad state more frequently
    const stateInterval = setInterval(updateGamepadState, 50);
    
    return () => {
      clearInterval(gamepadListInterval);
      clearInterval(stateInterval);
      window.removeEventListener("gamepadconnected", onConnect);
      window.removeEventListener("gamepaddisconnected", onDisconnect);
    };
  }, [selectedGamepadId]);

  return {
    // Available gamepads
    availableGamepads,
    selectedGamepadId,
    selectGamepad,
    
    // Gamepad state
    connected: gamepadState.connected,
    pressedInputs: gamepadState.pressedInputs,
    axisValues: gamepadState.axisValues,
    
    // Gamepad inputs (dynamic)
    gamepadInputs,
    
    // Mappings & actions
    mappings,
    isActionActive,
    getAxisValueForAction,
    getActionForInput,
    getInputLabelForMapping,
    
    // Remapping with preferred type parameter
    listenForNextInput,
    listeningFor,
  };
}