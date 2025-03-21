export function applyDeadzone(value: number, deadzone: number): number {
  if (Math.abs(value) < deadzone) {
    return 0;
  }
  return value;

}