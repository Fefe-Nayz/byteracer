"use client";
import { useEffect, useRef, useState } from "react";
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

export type ActionKey =
  | "forward"
  | "backward"
  | "turnRight"
  | "turnLeft"
  | "turnCameraRight"
  | "turnCameraLeft"
  | "turnCameraUp"
  | "turnCameraDown"
  | "use"
  | "pushToTalk"
  | "listen";

export interface ActionInfo {
  key: ActionKey;
  label: string;
  type: "button" | "axis" | "both";
  defaultMapping: {
    type: "button" | "axis";
    index: number;
  };
  allowSharedMappingWith?: ActionKey[]; // List of actions that can share the same input
  // New field for axis configuration
  axisConfig?: {
    defaultMin: number; // Minimum range (-1 to 1)1)
    defaultMax: number; // Maximum range (-1 to 1)
    inverted?: boolean; // Whether axis should be inverted by default
    normalize: "full" | "positive"; // How to normalize: full (-1 to 1) or positive (0 to 1)
    deadzone?: number; // Deadzone for axis input
  };
}

export type ActionGroupKey =
  | "speed"
  | "turn"
  | "turnCameraX"
  | "turnCameraY";

export interface ActionGroup {
  key: ActionGroupKey;
  actions: ActionKey[];
}

export const ACTION_GROUPS: ActionGroup[] = [
  {
    key: "speed",
    actions: ["forward", "backward"],
  },
  {
    key: "turn",
    actions: ["turnRight", "turnLeft"],
  },
  {
    key: "turnCameraX",
    actions: ["turnCameraRight", "turnCameraLeft"],
  },
  {
    key: "turnCameraY",
    actions: ["turnCameraUp", "turnCameraDown"],
  }
];

export const ACTIONS: ActionInfo[] = [
  {
    key: "forward",
    label: "Avancer",
    type: "both",
    defaultMapping: { type: "axis", index: 1 },
    allowSharedMappingWith: ["backward"],
    axisConfig: {
      defaultMin: -1.0,
      defaultMax: 0.0,
      inverted: true,
      normalize: "positive",
      deadzone: 0.1,
    },
  },
  {
    key: "backward",
    label: "Reculer",
    type: "both",
    defaultMapping: { type: "axis", index: 1 },
    allowSharedMappingWith: ["forward"],
    axisConfig: {
      defaultMin: 0.0,
      defaultMax: 1.0,
      inverted: false,
      normalize: "positive",
      deadzone: 0.1,
    },
  },
  {
    key: "turnRight",
    label: "Tourner à Droite",
    type: "both",
    defaultMapping: { type: "axis", index: 0 },
    allowSharedMappingWith: ["turnLeft"],
    axisConfig: {
      defaultMin: 0.0,
      defaultMax: 1.0,
      inverted: false,
      normalize: "positive",
      deadzone: 0.1,
    },
  },
  {
    key: "turnLeft",
    label: "Tourner à Gauche",
    type: "both",
    defaultMapping: { type: "axis", index: 0 },
    allowSharedMappingWith: ["turnRight"],
    axisConfig: {
      defaultMin: -1.0,
      defaultMax: 0.0,
      inverted: true,
      normalize: "positive",
      deadzone: 0.1,
    },
  },
  {
    key: "turnCameraRight",
    label: "Tourner la caméra à droite",
    type: "both",
    defaultMapping: { type: "axis", index: 2 },
    allowSharedMappingWith: ["turnCameraLeft"],
    axisConfig: {
      defaultMin: 0.0,
      defaultMax: 1.0,
      inverted: false,
      normalize: "positive",
      deadzone: 0.1,
    },
  },
  {
    key: "turnCameraLeft",
    label: "Tourner la caméra à gauche",
    type: "both",
    defaultMapping: { type: "axis", index: 2 },
    allowSharedMappingWith: ["turnCameraRight"],
    axisConfig: {
      defaultMin: -1.0,
      defaultMax: 0.0,
      inverted: true,
      normalize: "positive",
      deadzone: 0.1,
    },
  },
  {
    key: "turnCameraUp",
    label: "Tourner la caméra en haut",
    type: "both",
    defaultMapping: { type: "axis", index: 3 },
    allowSharedMappingWith: ["turnCameraDown"],
    axisConfig: {
      defaultMin: -1.0,
      defaultMax: 0.0,
      inverted: true,
      normalize: "positive",
      deadzone: 0.1,
    },
  },
  {
    key: "turnCameraDown",
    label: "Tourner la caméra en bas",
    type: "both",
    defaultMapping: { type: "axis", index: 3 },
    allowSharedMappingWith: ["turnCameraUp"],
    axisConfig: {
      defaultMin: 0.0,
      defaultMax: 1.0,
      inverted: false,
      normalize: "positive",
      deadzone: 0.1,
    },
  },
  {
    key: "use",
    label: "Utiliser",
    type: "button",
    defaultMapping: { type: "button", index: 2 },
  },
  {
    key: "pushToTalk",
    label: "Push to talk",
    type: "button",
    defaultMapping: { type: "button", index: 0 },
  },
  {
    key: "listen",
    label: "Écouter",
    type: "button",
    defaultMapping: { type: "button", index: 1 },
  },
];

// Update Mapping type - Fix the "both" type issue
type Mapping = Record<
  ActionKey,
  {
    type: "button" | "axis"; // Remove "both" from here - it's not a mapping type
    index: number;
    axisConfig?: {
      min: number;
      max: number;
      inverted: boolean;
      normalize: "full" | "positive";
      deadzone?: number; // Add deadzone property to the mapping
    };
  }
>;

// Updated type definition to fix the error
type StoredMappings = {
  [gamepadId: string]: Mapping;
} & {
  _resetFlag?: boolean; // Separate from the index signature
};

type GamepadState = {
  connected: boolean;
  pressedInputs: Set<string>;
  axisValues: number[];
  _lastUpdate?: number;
};

export function useGamepad() {
  const [availableGamepads, setAvailableGamepads] = useState<Gamepad[]>([]);
  const [selectedGamepadId, setSelectedGamepadId] = useState<string | null>(
    null
  );
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
  const [mappings, setMappings] = useState<Mapping>(() => {
    const defaultMappings = {} as Mapping;

    ACTIONS.forEach((action) => {
      const actionInfo = ACTIONS.find((a) => a.key === action.key);

      // Create mapping with correct type (button or axis, not both)
      const mapping: Mapping[ActionKey] = {
        type: action.defaultMapping.type, // This is already "button" or "axis", not "both"
        index: action.defaultMapping.index,
      };

      // Add axisConfig if this is an axis-type mapping
      if (action.defaultMapping.type === "axis") {
        // Use nullish coalescing for cleaner defaults
        mapping.axisConfig = {
          min: actionInfo?.axisConfig?.defaultMin ?? -1.0,
          max: actionInfo?.axisConfig?.defaultMax ?? 1.0,
          inverted: actionInfo?.axisConfig?.inverted ?? false,
          normalize: actionInfo?.axisConfig?.normalize ?? "full",
          deadzone: actionInfo?.axisConfig?.deadzone ?? 0.1, // Include deadzone in the default
        };
      }

      defaultMappings[action.key] = mapping;
    });

    return defaultMappings;
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
    initialAxisValues: [],
  });

  // Add state to track the current remapping type
  const [remappingType, setRemappingType] = useState<"button" | "axis">(
    "button"
  );

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
      // Fixed version with proper default mappings
    } else if (selectedGamepadId) {
      // Use default mappings from the ACTIONS array
      const defaultMappings = {} as Mapping;

      ACTIONS.forEach((action) => {
        const actionInfo = ACTIONS.find((a) => a.key === action.key);

        // Create mapping with correct type (button or axis, not both)
        const mapping: Mapping[ActionKey] = {
          type: action.defaultMapping.type, // This is already "button" or "axis", not "both"
          index: action.defaultMapping.index,
        };

        // Add axisConfig if this is an axis-type mapping
        if (action.defaultMapping.type === "axis") {
          // Use nullish coalescing for cleaner defaults
          mapping.axisConfig = {
            min: actionInfo?.axisConfig?.defaultMin ?? -1.0,
            max: actionInfo?.axisConfig?.defaultMax ?? 1.0,
            inverted: actionInfo?.axisConfig?.inverted ?? false,
            normalize: actionInfo?.axisConfig?.normalize ?? "full",
            deadzone: actionInfo?.axisConfig?.deadzone ?? 0.1, // Include deadzone in the default
          };
        }

        defaultMappings[action.key] = mapping;
      });

      setMappings(defaultMappings);
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
        if (
          JSON.stringify(prev[selectedGamepadId]) === JSON.stringify(mappings)
        ) {
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
            case 0:
              label = "A";
              break;
            case 1:
              label = "B";
              break;
            case 2:
              label = "X";
              break;
            case 3:
              label = "Y";
              break;
            case 4:
              label = "LB";
              break;
            case 5:
              label = "RB";
              break;
            case 6:
              label = "LT";
              break;
            case 7:
              label = "RT";
              break;
            case 8:
              label = "Select";
              break;
            case 9:
              label = "Start";
              break;
            case 10:
              label = "L3";
              break; // Left stick button
            case 11:
              label = "R3";
              break; // Right stick button
            case 12:
              label = "D-Pad Up";
              break;
            case 13:
              label = "D-Pad Down";
              break;
            case 14:
              label = "D-Pad Left";
              break;
            case 15:
              label = "D-Pad Right";
              break;
          }
        }

        buttons.push({
          id: `button-${i}`,
          type: "button",
          index: i,
          label,
        });
      }

      // Create axis inputs
      const axes: GamepadAxisInput[] = [];
      for (let i = 0; i < gamepad.axes.length; i++) {
        let label = "Axis " + i;
        // Standard mapping labels
        if (gamepad.mapping === "standard") {
          switch (i) {
            case 0:
              label = "Left Stick X";
              break;
            case 1:
              label = "Left Stick Y";
              break;
            case 2:
              label = "Right Stick X";
              break;
            case 3:
              label = "Right Stick Y";
              break;
          }
        }

        axes.push({
          id: `axis-${i}`,
          type: "axis",
          index: i,
          label,
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
  function listenForNextInput(
    action: ActionKey | null,
    preferredType?: "button" | "axis"
  ) {
    if (action === null) {
      console.log("Cancelling remap operation");
      setListeningFor(null);
      remappingRef.current = {
        active: false,
        action: null,
        actionType: null,
      };
      return;
    }

    // Find action type
    const actionInfo = ACTIONS.find((a) => a.key === action);

    // Use preferred type if specified, otherwise use action's default type
    const actionType = preferredType || actionInfo?.type || "button";

    // Update the remapping type state for UI display
    setRemappingType(actionType as "button" | "axis");

    console.log(`Now listening for ${actionType} input for action ${action}`);

    // Store initial axis values for proper detection
    const pads = navigator.getGamepads ? navigator.getGamepads() : [];
    const activePad = Array.from(pads).find(
      (g) => g && g.id === selectedGamepadId
    );
    const initialAxisValues = activePad ? [...activePad.axes] : [];

    setListeningFor(action);
    remappingRef.current = {
      active: true,
      action: action,
      actionType: actionType,
      initialAxisValues: initialAxisValues,
    };
  }

  // Check if an action is active
  function isActionActive(action: ActionKey): boolean {
    if (!gamepadState.connected) return false;
    const map = mappings[action];
    if (!map || map.index === -1) return false; // Check for -1 (unmapped)

    if (map.type === "button") {
      const id = `button-${map.index}`;
      return gamepadState.pressedInputs.has(id);
    } else if (map.type === "axis") {
      // For axis mapping, we need to process the axis value
      const val = gamepadState.axisValues[map.index] ?? 0;
      const deadzone = map.axisConfig?.deadzone ?? 0.1;
      
      // Apply deadzone threshold
      return Math.abs(val) > deadzone;
    }

    // Should never reach here, but better safe
    return false;
  }

  // Get the axis value for an action with range adjustments
  function getAxisValueForAction(
    action: ActionKey,
    applyConfig = true
  ): number | undefined {
    if (!gamepadState.connected) return 0;
    const map = mappings[action];
    if (!map || map.type !== "axis") return undefined;

    // Get raw value
    const rawValue = gamepadState.axisValues[map.index] ?? 0;

    // If we don't need to apply configuration, return raw value
    if (!applyConfig || !map.axisConfig) return rawValue;

    // Apply axis configuration
    const { min, max, inverted, normalize, deadzone = 0.1 } = map.axisConfig;

    // Apply deadzone
    const rawWithDeadzone = applyDeadzone(rawValue, deadzone);

    // First, clamp raw value between min and max
    const clampedValue = Math.max(min, Math.min(max, rawWithDeadzone));

    // Calculate the normalized value based on the mode
    if (normalize === "positive") {
      // For positive mode: map range to 0-1
      const rangeDiff = Math.abs(max - min);

      if (rangeDiff === 0) return 0; // Avoid division by zero

      // Calculate normalized position in range (0-1)
      let normalizedPos;

      if (!inverted) {
        // Normal mapping: lower bound → 0, upper bound → 1
        normalizedPos = (clampedValue - min) / rangeDiff;
      } else {
        // Inverted mapping: lower bound → 1, upper bound → 0
        normalizedPos = 1 - (clampedValue - min) / rangeDiff;
      }

      return normalizedPos;
    } else {
      // For full mode: map range to -1 to 1
      const rangeDiff = Math.abs(max - min);

      if (rangeDiff === 0) return 0; // Avoid division by zero

      // Map the value to -1 to 1 range
      const fullRangeValue = -1 + 2 * ((clampedValue - min) / rangeDiff); // Changed to const

      // Apply inversion if needed (simply flip the sign)
      return inverted ? -fullRangeValue : fullRangeValue;
    }
  }

  // Add a function to get raw axis value
  function getRawAxisValue(action: ActionKey): number | undefined {
    if (!gamepadState.connected) return 0;
    const map = mappings[action];
    if (!map || map.type !== "axis") return undefined;
    return gamepadState.axisValues[map.index] ?? 0;
  }

  // Find which action is mapped to a specific input
  function getActionForInput(
    type: "button" | "axis",
    index: number
  ): ActionKey | null {
    for (const [action, cfg] of Object.entries(mappings) as [
      ActionKey,
      { type: string; index: number }
    ][]) {
      if (cfg.type === type && cfg.index === index) {
        return action as ActionKey;
      }
    }
    return null;
  }

  // Improved findAllActionsUsingInput function to find ALL conflicts
  function findAllActionsUsingInput(
    type: "button" | "axis",
    index: number,
    currentMappings?: Mapping
  ): ActionKey[] {
    // Use provided mappings or fall back to the current state mappings
    const mappingsToCheck = currentMappings || mappings;
    const conflictingActions: ActionKey[] = [];

    for (const [action, cfg] of Object.entries(mappingsToCheck) as [
      ActionKey,
      { type: string; index: number }
    ][]) {
      if (cfg.type === type && cfg.index === index) {
        conflictingActions.push(action as ActionKey);
      }
    }
    return conflictingActions;
  }

  // Get label for input mapping
  function getInputLabelForMapping(mapping: {
    type: string;
    index: number;
  }): string {
    if (mapping.type === "button") {
      const found = gamepadInputs.buttons.find(
        (btn) => btn.index === mapping.index
      );
      return found ? found.label : "Unknown Button";
    } else if (mapping.type === "axis") {
      const found = gamepadInputs.axes.find(
        (axis) => axis.index === mapping.index
      );
      return found ? found.label : "Unknown Axis";
    }
    return "Unknown";
  }

  /** Polling function, called periodically. */
  function updateGamepadState() {
    const now = Date.now();
    if (listeningFor && now % 1000 < 50) {
      console.log("Still listening for:", listeningFor);
      console.log(
        "Current gamepad state:",
        gamepadState.connected ? "connected" : "disconnected",
        "Buttons pressed:",
        Array.from(gamepadState.pressedInputs)
      );
    }

    updateAvailableGamepads();

    if (!selectedGamepadId) {
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
    const activePad = Array.from(pads).find(
      (g) => g && g.id === selectedGamepadId
    );

    if (!activePad) {
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

      // For button-type actions or "both" type
      if (actionType === "button" || actionType === "both") {
        // Check each button directly
        for (let i = 0; i < activePad.buttons.length; i++) {
          const buttonState = activePad.buttons[i];

          // Check if pressed or value > 0.5 (for analog buttons/triggers)
          if (buttonState.pressed || buttonState.value > 0.5) {
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
            // Map to axis type
            remapToAxis(action, i);
            return; // Exit after successful remap
          }
        }
      }
    }

    // Update state if changed
    const prevJSON = JSON.stringify({
      connected: gamepadState.connected,
      pressedInputs: Array.from(gamepadState.pressedInputs),
      axisValues: gamepadState.axisValues,
    });

    const newJSON = JSON.stringify({
      connected: newState.connected,
      pressedInputs: Array.from(newState.pressedInputs),
      axisValues: newState.axisValues,
    });

    if (prevJSON !== newJSON) {
      setGamepadState(newState);
    }
  }

  function remapToButton(action: ActionKey, buttonIndex: number) {
    // Update mapping, handling any conflicts within the setMappings callback
    setMappings((prev) => {
      // Find ALL actions currently using this button
      const conflictingActions = findAllActionsUsingInput(
        "button",
        buttonIndex,
        prev
      );
      const newMappings = { ...prev };

      // Current action info
      const newActionInfo = ACTIONS.find((a) => a.key === action);

      // Process each conflicting action
      conflictingActions.forEach((conflictingAction) => {
        // Skip if it's the action we're currently mapping
        if (conflictingAction === action) return;

        const existingActionInfo = ACTIONS.find(
          (a) => a.key === conflictingAction
        );

        // Check if BIDIRECTIONAL sharing is allowed
        const newAllowsExisting =
          newActionInfo?.allowSharedMappingWith?.includes(conflictingAction) ||
          false;
        const existingAllowsNew =
          existingActionInfo?.allowSharedMappingWith?.includes(action) || false;

        const sharingAllowed = newAllowsExisting && existingAllowsNew;

        // Only clear the conflicting mapping if sharing is not allowed
        if (!sharingAllowed) {
          newMappings[conflictingAction] = { type: "button", index: -1 }; // -1 means unassigned
        }
      });

      // Assign the button to the current action
      newMappings[action] = { type: "button", index: buttonIndex };
      return newMappings;
    });

    // Reset remapping state
    remappingRef.current = {
      active: false,
      action: null,
      actionType: null,
    };
    setListeningFor(null);
  }

  function remapToAxis(action: ActionKey, axisIndex: number) {
    // Update mapping, handling any conflicts within the setMappings callback
    setMappings((prev) => {
      // Find ALL actions currently using this axis
      const conflictingActions = findAllActionsUsingInput(
        "axis",
        axisIndex,
        prev
      );
      const newMappings = { ...prev };

      // Current action info - using directly without storing in variable to avoid unused variable

      // Process each conflicting action
      conflictingActions.forEach((conflictingAction) => {
        // Skip if it's the action we're currently mapping
        if (conflictingAction === action) return;

        const existingActionInfo = ACTIONS.find(
          (a) => a.key === conflictingAction
        );

        // Check if BIDIRECTIONAL sharing is allowed
        const newActionInfo = ACTIONS.find((a) => a.key === action); // moved here so it's used
        const newAllowsExisting =
          newActionInfo?.allowSharedMappingWith?.includes(conflictingAction) ||
          false;
        const existingAllowsNew =
          existingActionInfo?.allowSharedMappingWith?.includes(action) || false;

        const sharingAllowed = newAllowsExisting && existingAllowsNew;

        // Only clear the conflicting mapping if sharing is not allowed
        if (!sharingAllowed) {
          newMappings[conflictingAction] = { type: "axis", index: -1 }; // -1 means unassigned
        }
      });

      // Get the action info to access default axis configuration
      const actionInfo = ACTIONS.find((a) => a.key === action);

      // Assign the axis to the current action WITH proper axis config
      newMappings[action] = {
        type: "axis",
        index: axisIndex,
        // Include the axis configuration from the ACTIONS array
        axisConfig: {
          min: actionInfo?.axisConfig?.defaultMin ?? -1.0,
          max: actionInfo?.axisConfig?.defaultMax ?? 1.0,
          inverted: actionInfo?.axisConfig?.inverted ?? false,
          normalize: actionInfo?.axisConfig?.normalize ?? "full",
          deadzone: actionInfo?.axisConfig?.deadzone ?? 0.1, // Include deadzone
        },
      };
      return newMappings;
    });

    // Reset remapping state
    remappingRef.current = {
      active: false,
      action: null,
      actionType: null,
    };
    setListeningFor(null);
  }

  // Set up event listeners and polling
  useEffect(() => {
    function onConnect() {
      updateAvailableGamepads();
    }

    function onDisconnect(e: GamepadEvent) {
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
    const stateInterval = setInterval(updateGamepadState, 10);

    return () => {
      clearInterval(gamepadListInterval);
      clearInterval(stateInterval);
      window.removeEventListener("gamepadconnected", onConnect);
      window.removeEventListener("gamepaddisconnected", onDisconnect);
    };
  }, [selectedGamepadId]);

  // Make sure this function accepts 'middle' parameter
  function setAxisConfig(
    action: ActionKey,
    config: {
      min: number;
      max: number;
      inverted: boolean;
      normalize: "full" | "positive";
      deadzone?: number; // Add deadzone to config type
    }
  ) {
    setMappings((prev) => {
      const newMappings = { ...prev };
      const currentMapping = newMappings[action];

      if (currentMapping && currentMapping.type === "axis") {
        newMappings[action] = {
          ...currentMapping,
          axisConfig: config,
        };
      }

      return newMappings;
    });
  }

  // Helper function to apply deadzone
  function applyDeadzone(value: number, deadzone: number): number {
    // Calculate the absolute value
    const absValue = Math.abs(value);

    // If under deadzone threshold, return 0
    if (absValue < deadzone) {
      return 0;
    }

    // Otherwise, rescale the value to remove the deadzone
    // This remaps the range [deadzone, 1] to [0, 1] with the same sign
    const sign = value >= 0 ? 1 : -1;
    return sign * ((absValue - deadzone) / (1 - deadzone));
  }

  // Add a function to reset mappings
  function resetAllMappings() {
    if (listeningFor) {
      listenForNextInput(null);
    }
    
    // Create default mappings for reference
    const defaultMappings = {} as Mapping;

    ACTIONS.forEach((action) => {
      const actionInfo = ACTIONS.find((a) => a.key === action.key);

      // Create mapping with correct type (button or axis, not both)
      const mapping: Mapping[ActionKey] = {
        type: action.defaultMapping.type,
        index: action.defaultMapping.index,
      };

      // Add axisConfig if this is an axis-type mapping
      if (action.defaultMapping.type === "axis") {
        mapping.axisConfig = {
          min: actionInfo?.axisConfig?.defaultMin ?? -1.0,
          max: actionInfo?.axisConfig?.defaultMax ?? 1.0,
          inverted: actionInfo?.axisConfig?.inverted ?? false,
          normalize: actionInfo?.axisConfig?.normalize ?? "full",
          deadzone: actionInfo?.axisConfig?.deadzone ?? 0.1,
        };
      }

      defaultMappings[action.key] = mapping;
    });

    // Reset mappings to default
    setMappings(defaultMappings);
    
    // Set reset flag while preserving type compatibility
    // We need to keep the gamepad mappings structure intact
    const emptiedMappings: StoredMappings = {};
    if (selectedGamepadId) {
      emptiedMappings[selectedGamepadId] = defaultMappings;
    }
    
    // Add the reset flag
    setStoredMappings({
      ...emptiedMappings,
      _resetFlag: true,
    } as StoredMappings);
    
  }

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
    getRawAxisValue,
    getActionForInput,
    getInputLabelForMapping,

    // Remapping with preferred type parameter
    listenForNextInput,
    listeningFor,
    remappingType,

    setAxisConfig,
    resetAllMappings, // Expose the reset function

    // Action definitions and groupings
    ACTIONS,
    ACTION_GROUPS,
  };
}
