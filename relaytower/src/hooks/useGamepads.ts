export function useGamepads() {
  const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
  return gamepads;
}