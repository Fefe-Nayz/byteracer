import { create } from 'zustand'

export const useGamepad = create<{
  gamepad: Gamepad | null
  setGamepad: (gamepad: Gamepad) => void
}>((set) => ({
  gamepad: null,
  setGamepad: (gamepad: Gamepad) => set({ gamepad }),
}))
