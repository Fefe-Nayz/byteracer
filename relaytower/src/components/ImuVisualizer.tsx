"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { Button } from "./ui/button";

interface Quat {
  w: number;
  x: number;
  y: number;
  z: number;
}

interface CircuitDebug {
  enabled: boolean;
  imuActive: boolean;
  headingReference: number;
  currentHeading?: number;
  headingError: number;
  steeringCommand: number;
  integral: number;
  gyroRateZ?: number;
  driveSpeed?: number;
  headingKp: number;
  headingKi: number;
  maxSteeringDeg: number;
  turnActive: boolean;
  turnStartYaw: number;
  turnTargetDeg: number;
  turnGoalDelta: number;
  turnCurrentDelta: number;
  turnStartMagHeading?: number | null;
  turnTargetMagHeading?: number | null;
  turnFinalMagHeading?: number | null;
  turnMagDelta?: number | null;
  turnMagError?: number | null;
  turnAppliedMagError?: number | null;
  turnMagAgreementError?: number | null;
  turnReferenceSource?: string;
  turnInPlace?: boolean;
}

interface ImuVisualizerProps {
  quaternion?: Quat;
  available: boolean;
  circuit?: CircuitDebug;
  circuitModeActive?: boolean;
  speed?: number;
  heading?: number;
  magHeading?: number;
  gyroYaw?: number;
  magnetometer?: boolean;
  mountOrientation?: string;
}

const ZERO_STORAGE_KEY = "byteracer-imu-zero-quat";
const DEG2RAD = Math.PI / 180;
const TRAIL_MAX_POINTS = 900;
const TRAIL_SPEED_SCALE = 4.0;

interface TrailPoint {
  x: number;
  y: number;
}

// Build the robot car in the IMU body frame: X = forward (nose), Y = left,
// Z = up. Returns the group plus the front wheels so they can be steered.
function buildRobot(): { group: THREE.Group; frontWheels: THREE.Mesh[] } {
  const group = new THREE.Group();

  const bodyMat = new THREE.MeshStandardMaterial({
    color: 0x0891b2,
    metalness: 0.3,
    roughness: 0.6,
  });
  const darkMat = new THREE.MeshStandardMaterial({
    color: 0x0e1116,
    metalness: 0.2,
    roughness: 0.8,
  });
  const frontMat = new THREE.MeshStandardMaterial({
    color: 0xf59e0b,
    metalness: 0.2,
    roughness: 0.5,
    emissive: 0x6b4500,
    emissiveIntensity: 0.4,
  });
  const wheelMat = new THREE.MeshStandardMaterial({
    color: 0x111827,
    metalness: 0.1,
    roughness: 0.9,
  });
  const frontWheelMat = new THREE.MeshStandardMaterial({
    color: 0x2563eb,
    metalness: 0.1,
    roughness: 0.85,
  });

  const chassis = new THREE.Mesh(new THREE.BoxGeometry(2.2, 1.4, 0.4), bodyMat);
  chassis.position.z = 0.35;
  group.add(chassis);

  const cabin = new THREE.Mesh(new THREE.BoxGeometry(1.0, 1.1, 0.45), darkMat);
  cabin.position.set(-0.25, 0, 0.72);
  group.add(cabin);

  const nose = new THREE.Mesh(new THREE.ConeGeometry(0.28, 0.6, 4), frontMat);
  nose.rotation.z = -Math.PI / 2;
  nose.position.set(1.35, 0, 0.4);
  group.add(nose);

  const wheelGeo = new THREE.CylinderGeometry(0.32, 0.32, 0.22, 20);
  const frontWheels: THREE.Mesh[] = [];
  const wheels: [number, number, number, boolean][] = [
    [0.75, 0.75, 0.32, true],
    [0.75, -0.75, 0.32, true],
    [-0.75, 0.75, 0.32, false],
    [-0.75, -0.75, 0.32, false],
  ];
  for (const [x, y, z, isFront] of wheels) {
    const wheel = new THREE.Mesh(wheelGeo, isFront ? frontWheelMat : wheelMat);
    wheel.position.set(x, y, z);
    group.add(wheel);
    if (isFront) frontWheels.push(wheel);
  }

  return { group, frontWheels };
}

function fmt(value: number | undefined, digits = 1) {
  if (value === undefined || value === null || Number.isNaN(value)) return "–";
  return value.toFixed(digits);
}

function compassDegrees(value: number | undefined) {
  if (value === undefined || value === null || Number.isNaN(value)) return undefined;
  return ((value % 360) + 360) % 360;
}

function normalizeAngle(value: number) {
  return ((value + 180) % 360 + 360) % 360 - 180;
}

export default function ImuVisualizer({
  quaternion,
  available,
  circuit,
  circuitModeActive = false,
  speed,
  heading,
  magHeading,
  gyroYaw,
  magnetometer,
  mountOrientation,
}: ImuVisualizerProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const quatRef = useRef<Quat>({ w: 1, x: 0, y: 0, z: 0 });
  const steerRef = useRef(0); // latest steering command in degrees
  const topDownRef = useRef(false);
  const yawRef = useRef(0);
  const speedRef = useRef(0);
  const driveSpeedRef = useRef(0);
  const pathRef = useRef<TrailPoint[]>([{ x: 0, y: 0 }]);
  const poseRef = useRef({ x: 0, y: 0 });
  const baseYawRef = useRef(0);
  const lastPathTimeRef = useRef(0);
  const wasCircuitRef = useRef(false);
  const trailDirtyRef = useRef(true);
  const zeroRef = useRef<THREE.Quaternion>(new THREE.Quaternion());
  const [hasZero, setHasZero] = useState(false);
  const [trailPoints, setTrailPoints] = useState(1);
  const zeroStorageKey = `${ZERO_STORAGE_KEY}:${mountOrientation || "default"}`;

  if (quaternion) quatRef.current = quaternion;
  steerRef.current = circuit?.steeringCommand ?? 0;
  topDownRef.current = !!circuitModeActive;
  yawRef.current = circuit?.currentHeading ?? gyroYaw ?? heading ?? 0;
  speedRef.current = Math.abs(speed ?? 0);
  driveSpeedRef.current = Math.max(0, circuit?.driveSpeed ?? 0);

  const resetTrail = useCallback(() => {
    pathRef.current = [{ x: 0, y: 0 }];
    poseRef.current = { x: 0, y: 0 };
    baseYawRef.current = yawRef.current;
    lastPathTimeRef.current = 0;
    trailDirtyRef.current = true;
    setTrailPoints(1);
  }, []);

  useEffect(() => {
    if (!available || !circuitModeActive) {
      wasCircuitRef.current = false;
      lastPathTimeRef.current = 0;
      return;
    }

    if (!wasCircuitRef.current) {
      resetTrail();
      wasCircuitRef.current = true;
      return;
    }

    const now = performance.now();
    if (!lastPathTimeRef.current) {
      lastPathTimeRef.current = now;
      return;
    }

    const dt = Math.min(0.25, Math.max(0, (now - lastPathTimeRef.current) / 1000));
    lastPathTimeRef.current = now;

    const driveSpeed = driveSpeedRef.current;
    const measuredSpeed = speedRef.current;
    const pathSpeed =
      driveSpeed > 0.01
        ? Math.max(driveSpeed, measuredSpeed)
        : measuredSpeed > 0.02
        ? measuredSpeed
        : 0;

    if (dt <= 0 || pathSpeed <= 0) return;

    const yawRad = normalizeAngle(yawRef.current - baseYawRef.current) * DEG2RAD;
    const distance = pathSpeed * TRAIL_SPEED_SCALE * dt;
    const pose = poseRef.current;
    pose.x += Math.cos(yawRad) * distance;
    pose.y -= Math.sin(yawRad) * distance;

    const points = pathRef.current;
    const last = points[points.length - 1];
    const dx = pose.x - last.x;
    const dy = pose.y - last.y;
    if (Math.hypot(dx, dy) > 0.015) {
      points.push({ x: pose.x, y: pose.y });
      if (points.length > TRAIL_MAX_POINTS) points.shift();
      trailDirtyRef.current = true;
      setTrailPoints(points.length);
    }
  }, [
    available,
    circuitModeActive,
    circuit?.currentHeading,
    circuit?.driveSpeed,
    gyroYaw,
    heading,
    resetTrail,
    speed,
  ]);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    try {
      const saved = localStorage.getItem(zeroStorageKey);
      if (saved) {
        const arr = JSON.parse(saved) as number[];
        if (Array.isArray(arr) && arr.length === 4) {
          zeroRef.current.fromArray(arr);
          setHasZero(true);
        }
      }
    } catch {
      /* ignore malformed storage */
    }

    const width = mount.clientWidth || 320;
    const height = 240;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
    camera.position.set(4.6, 3.2, 5.0);
    camera.lookAt(0, 0.5, 0);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height);
    mount.appendChild(renderer.domElement);

    scene.add(new THREE.HemisphereLight(0xffffff, 0x404050, 1.1));
    const dir = new THREE.DirectionalLight(0xffffff, 1.2);
    dir.position.set(5, 8, 6);
    scene.add(dir);

    const grid = new THREE.GridHelper(12, 24, 0x0891b2, 0x334155);
    (grid.material as THREE.Material).opacity = 0.35;
    (grid.material as THREE.Material).transparent = true;
    scene.add(grid);

    const pivot = new THREE.Group();
    pivot.rotation.x = -Math.PI / 2;
    scene.add(pivot);

    const trailMaterial = new THREE.LineBasicMaterial({
      color: 0xef4444,
      linewidth: 2,
      transparent: true,
      opacity: 0.95,
    });
    const trailLine = new THREE.Line(new THREE.BufferGeometry(), trailMaterial);
    trailLine.visible = false;
    pivot.add(trailLine);

    const { group: robot, frontWheels } = buildRobot();
    pivot.add(robot);

    const qCurrent = new THREE.Quaternion();
    const qDisplay = new THREE.Quaternion();
    const qZeroInv = new THREE.Quaternion();
    const qYawOnly = new THREE.Quaternion();
    const normalCameraPos = new THREE.Vector3(4.6, 3.2, 5.0);
    const normalLookAt = new THREE.Vector3(0, 0.5, 0);
    const topDownTarget = new THREE.Vector3();
    const topDownCameraPos = new THREE.Vector3();
    const robotLocalTarget = new THREE.Vector3();
    const yawAxis = new THREE.Vector3(0, 0, 1);

    let frameId = 0;
    let shownSteer = 0;
    const animate = () => {
      const topDown = topDownRef.current;

      if (trailDirtyRef.current) {
        const positions = pathRef.current.map(
          (p) => new THREE.Vector3(p.x, p.y, 0.035)
        );
        trailLine.geometry.dispose();
        trailLine.geometry = new THREE.BufferGeometry().setFromPoints(positions);
        trailDirtyRef.current = false;
      }

      if (topDown) {
        const pose = poseRef.current;
        robot.position.lerp(robotLocalTarget.set(pose.x, pose.y, 0), 0.35);
        const yawRad = normalizeAngle(yawRef.current - baseYawRef.current) * DEG2RAD;
        qYawOnly.setFromAxisAngle(yawAxis, yawRad);
        robot.quaternion.slerp(qYawOnly, 0.35);
        trailLine.visible = true;

        pivot.updateWorldMatrix(true, false);
        topDownTarget.set(pose.x, pose.y, 0).applyMatrix4(pivot.matrixWorld);
        topDownCameraPos.set(topDownTarget.x, 13.5, topDownTarget.z + 0.001);
        camera.up.set(0, 0, -1);
        camera.position.lerp(topDownCameraPos, 0.12);
        camera.lookAt(topDownTarget);
      } else {
        robot.position.lerp(robotLocalTarget.set(0, 0, 0), 0.2);
        const q = quatRef.current;
        qCurrent.set(q.x, q.y, q.z, q.w);
        qZeroInv.copy(zeroRef.current).invert();
        qDisplay.copy(qZeroInv).multiply(qCurrent);
        robot.quaternion.slerp(qDisplay, 0.25);
        trailLine.visible = false;

        camera.up.set(0, 1, 0);
        camera.position.lerp(normalCameraPos, 0.08);
        camera.lookAt(normalLookAt);
      }

      // Steer the (blue) front wheels by the live servo command so you can see
      // how the controller is correcting the course.
      const targetSteer = -steerRef.current * DEG2RAD;
      shownSteer += (targetSteer - shownSteer) * 0.25;
      for (const w of frontWheels) w.rotation.z = shownSteer;

      renderer.render(scene, camera);
      frameId = requestAnimationFrame(animate);
    };
    animate();

    const handleResize = () => {
      const w = mount.clientWidth || width;
      camera.aspect = w / height;
      camera.updateProjectionMatrix();
      renderer.setSize(w, height);
    };
    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(mount);

    return () => {
      cancelAnimationFrame(frameId);
      resizeObserver.disconnect();
      renderer.dispose();
      if (renderer.domElement.parentNode === mount) {
        mount.removeChild(renderer.domElement);
      }
      scene.traverse((obj) => {
        if (obj instanceof THREE.Mesh) {
          obj.geometry.dispose();
          const mat = obj.material;
          if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
          else mat.dispose();
        }
      });
      trailLine.geometry.dispose();
      trailMaterial.dispose();
    };
  }, [zeroStorageKey]);

  const setLevel = () => {
    const q = quatRef.current;
    zeroRef.current.set(q.x, q.y, q.z, q.w);
    try {
      localStorage.setItem(
        zeroStorageKey,
        JSON.stringify(zeroRef.current.toArray())
      );
    } catch {
      /* ignore storage errors */
    }
    setHasZero(true);
  };

  const resetLevel = () => {
    zeroRef.current.identity();
    try {
      localStorage.removeItem(zeroStorageKey);
    } catch {
      /* ignore */
    }
    setHasZero(false);
  };

  const showCircuit = !!circuit?.enabled;
  const topDownMode = available && circuitModeActive;
  const turnPct =
    circuit && circuit.turnTargetDeg > 0
      ? Math.min(100, (circuit.turnCurrentDelta / circuit.turnTargetDeg) * 100)
      : 0;
  const compassHeading = compassDegrees(magnetometer ? magHeading : heading);
  const compassNeedle = compassHeading === undefined ? 0 : -compassHeading;

  return (
    <div className="space-y-2">
      <div
        ref={mountRef}
        className="relative w-full overflow-hidden rounded-md bg-gradient-to-b from-slate-100 to-slate-200 dark:from-slate-900 dark:to-slate-950"
        style={{ height: 240 }}
      >
        {!available && (
          <div className="absolute inset-0 flex items-center justify-center bg-background/60 text-xs font-medium text-muted-foreground">
            IMU unavailable
          </div>
        )}

        {/* Circuit-mode control overlay */}
        {available && showCircuit && (
          <div className="absolute left-2 top-2 right-2 rounded bg-black/55 p-2 text-[10px] leading-tight text-white backdrop-blur-sm">
            {circuit?.turnActive ? (
              <div className="space-y-1">
                <div className="flex items-center justify-between font-semibold text-amber-300">
                  <span>TURNING</span>
                  <span>
                    {fmt(circuit.turnCurrentDelta, 0)}° / {fmt(circuit.turnTargetDeg, 0)}°
                  </span>
                </div>
                <div className="flex justify-between text-white/80">
                  <span>rate {fmt(circuit.gyroRateZ, 0)}°/s</span>
                  <span>yaw {fmt(circuit.currentHeading, 0)}°</span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded bg-white/20">
                  <div
                    className="h-full bg-amber-400 transition-[width] duration-100"
                    style={{ width: `${turnPct}%` }}
                  />
                </div>
              </div>
            ) : (
              <div className="space-y-1">
                <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
                  <div className="flex items-center gap-1">
                    <span
                      className={`inline-block h-1.5 w-1.5 rounded-full ${
                        circuit?.imuActive ? "bg-green-400" : "bg-gray-500"
                      }`}
                    />
                    <span>{circuit?.imuActive ? "Heading hold" : "Hold idle"}</span>
                  </div>
                  <div className="text-right">
                    steer <span className="font-semibold">{fmt(circuit?.steeringCommand)}°</span>
                  </div>
                  <div>
                    ref{" "}
                    <span className="font-semibold">{fmt(circuit?.headingReference, 0)}°</span>
                  </div>
                  <div className="text-right">
                    cur{" "}
                    <span className="font-semibold">{fmt(circuit?.currentHeading, 0)}°</span>
                  </div>
                  <div>
                    err <span className="font-semibold">{fmt(circuit?.headingError)}°</span>
                  </div>
                  <div className="text-right">
                    rate <span className="font-semibold">{fmt(circuit?.gyroRateZ, 0)}°/s</span>
                  </div>
                  <div>
                    ∫ <span className="font-semibold">{fmt(circuit?.integral)}</span>
                  </div>
                  <div className="text-right">
                    spd <span className="font-semibold">{fmt((circuit?.driveSpeed ?? 0) * 100, 0)}%</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {topDownMode && (
          <div className="absolute left-2 bottom-2 rounded bg-black/55 px-2 py-1 text-[10px] text-white backdrop-blur-sm">
            <div className="font-semibold text-red-300">Top-down trail</div>
            <div className="text-white/75">{trailPoints} pts · relative path</div>
          </div>
        )}

        {/* Live steering bar (servo angle) */}
        {available && showCircuit && !circuit?.turnActive && (
          <div className="absolute bottom-2 left-1/2 w-32 -translate-x-1/2">
            <div className="relative h-1.5 w-full rounded bg-white/25">
              <div className="absolute left-1/2 top-1/2 h-3 w-px -translate-y-1/2 bg-white/60" />
              <div
                className="absolute top-1/2 h-1.5 rounded bg-cyan-400"
                style={{
                  left: "50%",
                  width: `${Math.min(
                    50,
                    (Math.abs(circuit?.steeringCommand ?? 0) /
                      (circuit?.maxSteeringDeg || 30)) *
                      50
                  )}%`,
                  transform: `translateY(-50%) ${
                    (circuit?.steeringCommand ?? 0) < 0 ? "translateX(-100%)" : ""
                  }`,
                }}
              />
            </div>
          </div>
        )}

        {available && (
          <div className="absolute bottom-2 right-2 flex items-center gap-2 rounded bg-black/55 px-2 py-1 text-[10px] text-white backdrop-blur-sm">
            <div className="relative h-11 w-11 rounded-full border border-white/45 bg-white/10">
              <div className="absolute left-1/2 top-1 h-1 w-px -translate-x-1/2 bg-white/60" />
              <div className="absolute bottom-1 left-1/2 h-1 w-px -translate-x-1/2 bg-white/35" />
              <div className="absolute left-1 top-1/2 h-px w-1 -translate-y-1/2 bg-white/35" />
              <div className="absolute right-1 top-1/2 h-px w-1 -translate-y-1/2 bg-white/35" />
              <div
                className="absolute left-1/2 top-1/2 h-8 w-0.5 origin-center rounded bg-amber-300"
                style={{ transform: `translate(-50%, -50%) rotate(${compassNeedle}deg)` }}
              >
                <div className="absolute -top-1 left-1/2 h-2 w-2 -translate-x-1/2 rotate-45 bg-amber-300" />
              </div>
              <div className="absolute left-1/2 top-1/2 h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white" />
            </div>
            <div className="min-w-14 leading-tight">
              <div className="font-semibold">{magnetometer ? "MAG" : "YAW"}</div>
              <div>{fmt(compassHeading, 0)}°</div>
              <div className="text-white/60">gyro {fmt(gyroYaw, 0)}°</div>
            </div>
          </div>
        )}
      </div>

      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          className="h-7 text-xs"
          onClick={setLevel}
          disabled={!available}
          title="Capture the current orientation as the level/forward reference"
        >
          Set as level
        </Button>
        {topDownMode && (
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={resetTrail}
            title="Clear the top-down circuit trail"
          >
            Clear trail
          </Button>
        )}
        {hasZero && (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs"
            onClick={resetLevel}
            title="Clear the saved level reference"
          >
            Reset
          </Button>
        )}
        <span className="ml-auto text-[10px] text-muted-foreground">
          {hasZero ? "Leveled" : "Place robot flat, then Set as level"}
        </span>
      </div>
    </div>
  );
}
