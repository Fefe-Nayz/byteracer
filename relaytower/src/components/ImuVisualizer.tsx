"use client";

import { useEffect, useRef, useState } from "react";
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
}

interface ImuVisualizerProps {
  quaternion?: Quat;
  available: boolean;
  circuit?: CircuitDebug;
}

const ZERO_STORAGE_KEY = "byteracer-imu-zero-quat";
const DEG2RAD = Math.PI / 180;

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

export default function ImuVisualizer({
  quaternion,
  available,
  circuit,
}: ImuVisualizerProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const quatRef = useRef<Quat>({ w: 1, x: 0, y: 0, z: 0 });
  const steerRef = useRef(0); // latest steering command in degrees
  const zeroRef = useRef<THREE.Quaternion>(new THREE.Quaternion());
  const [hasZero, setHasZero] = useState(false);

  if (quaternion) quatRef.current = quaternion;
  steerRef.current = circuit?.steeringCommand ?? 0;

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    try {
      const saved = localStorage.getItem(ZERO_STORAGE_KEY);
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

    const { group: robot, frontWheels } = buildRobot();
    pivot.add(robot);

    const qCurrent = new THREE.Quaternion();
    const qDisplay = new THREE.Quaternion();
    const qZeroInv = new THREE.Quaternion();

    let frameId = 0;
    let shownSteer = 0;
    const animate = () => {
      const q = quatRef.current;
      qCurrent.set(q.x, q.y, q.z, q.w);
      qZeroInv.copy(zeroRef.current).invert();
      qDisplay.copy(qZeroInv).multiply(qCurrent);
      robot.quaternion.slerp(qDisplay, 0.25);

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
    };
  }, []);

  const setLevel = () => {
    const q = quatRef.current;
    zeroRef.current.set(q.x, q.y, q.z, q.w);
    try {
      localStorage.setItem(
        ZERO_STORAGE_KEY,
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
      localStorage.removeItem(ZERO_STORAGE_KEY);
    } catch {
      /* ignore */
    }
    setHasZero(false);
  };

  const showCircuit = !!circuit?.enabled;
  const turnPct =
    circuit && circuit.turnTargetDeg > 0
      ? Math.min(100, (circuit.turnCurrentDelta / circuit.turnTargetDeg) * 100)
      : 0;

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
