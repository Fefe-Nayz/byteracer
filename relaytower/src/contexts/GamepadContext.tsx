"use client";
import { useGamepad } from "@/hooks/useGamepad";
import { createContext, ReactNode, useContext } from "react";

// Define the context type explicitly
type GamepadContextType = ReturnType<typeof useGamepad>;

// Create context with a more specific type
const GamepadContext = createContext<GamepadContextType | undefined>(undefined);

export function GamepadProvider({ children }: { children: ReactNode }) {
  // Create a single instance of the gamepad hook
  const gamepadState = useGamepad();

  // Make the context value explicit
  const contextValue: GamepadContextType = gamepadState;

  // console.log(
  //   "GamepadProvider rendering - listening for:",
  //   gamepadState.listeningFor
  // );

  return (
    <GamepadContext.Provider value={contextValue}>
      {children}
    </GamepadContext.Provider>
  );
}

export function useGamepadContext() {
  const context = useContext(GamepadContext);
  if (context === undefined) {
    throw new Error("useGamepadContext must be used within a GamepadProvider");
  }
  return context;
}
