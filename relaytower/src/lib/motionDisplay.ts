import type { SensorData } from "@/contexts/WebSocketContext";

export interface MotionBarValues {
  speed: number;
  turn: number;
  acceleration: number;
  imuMode: boolean;
  speedLabel: string;
  turnLabel: string;
  accelLabel: string;
  turnCaption: string;
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

/** Normalized -1..1 bar values plus human labels for SensorData / video overlay. */
export function getMotionBarValues(sensorData: SensorData): MotionBarValues {
  const imuReady = !!sensorData.imu?.available;

  if (imuReady) {
    const gyroZ = sensorData.imu?.gyro?.z ?? 0;
    const accelG = sensorData.imu?.forwardAccelG ?? 0;
    const turn = clamp(gyroZ / 120, -1, 1);
    const acceleration = clamp(accelG / 0.25, -1, 1);
    // Prefer backend IMU speed estimate; fall back to live activity proxy.
    const speed =
      sensorData.motionSource === "imu"
        ? (sensorData.speed ?? 0)
        : clamp(Math.abs(accelG) * 3 + Math.abs(gyroZ) / 150, 0, 1);

    return {
      speed,
      turn,
      acceleration,
      imuMode: true,
      speedLabel: `${Math.round(Math.abs(speed) * 100)}%`,
      turnLabel: `${gyroZ.toFixed(0)}°/s`,
      accelLabel: `${accelG >= 0 ? "+" : ""}${accelG.toFixed(2)}g`,
      turnCaption: "Yaw rate",
    };
  }

  const speed = sensorData.speed ?? 0;
  const turn = sensorData.turn ?? 0;
  const acceleration = sensorData.acceleration ?? 0;

  return {
    speed,
    turn,
    acceleration,
    imuMode: false,
    speedLabel: `${Math.round(Math.abs(speed) * 100)}%`,
    turnLabel: `${Math.round(Math.abs(turn) * 100)}%`,
    accelLabel: `${Math.round(Math.abs(acceleration) * 100)}%`,
    turnCaption: "Turn",
  };
}
