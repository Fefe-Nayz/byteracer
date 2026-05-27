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

/** Normalized -1..1 bar values plus human labels for SensorData / video overlay. */
export function getMotionBarValues(sensorData: SensorData): MotionBarValues {
  const speed = sensorData.speed ?? 0;
  const turn = sensorData.turn ?? 0;
  const acceleration = sensorData.acceleration ?? 0;
  const imuMode = sensorData.motionSource === "imu" && !!sensorData.imu?.available;

  if (imuMode) {
    const gyroZ = sensorData.imu?.gyro?.z ?? 0;
    const accelG = sensorData.imu?.forwardAccelG ?? 0;
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
