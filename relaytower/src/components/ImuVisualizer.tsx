"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { Button } from "./ui/button";

interface ImuVisualizerProps {
  roll: number;
  pitch: number;
  yaw: number;
  available: boolean;
}

const ZERO_STORAGE_KEY = "byteracer-imu-zero-quat";
const DEG2RAD = Math.PI / 180;

// Build the orientation quaternion from the IMU euler angles. Mapping:
//   yaw   -> world up (Y) : heading
//   pitch -> lateral (X)  : nose up/down
//   roll  -> longitudinal (Z) : banking
// Flip a sign here if a real-robot test shows an axis rotating the wrong way.
function quatFromEuler(rollDeg: number, pitchDeg: number, yawDeg: number) {
  const euler = new THREE.Euler(
    pitchDeg * DEG2RAD,
    yawDeg * DEG2RAD,
    rollDeg * DEG2RAD,
    "YXZ"
  );
  return new THREE.Quaternion().setFromEuler(euler);
}

// Build the little robot car. Returns the group to add to the scene.
function buildRobot(): THREE.Group {
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

  // Chassis (length along Z = forward, width along X, height along Y).
  const chassis = new THREE.Mesh(new THREE.BoxGeometry(1.4, 0.4, 2.2), bodyMat);
  chassis.position.y = 0.35;
  group.add(chassis);

  // Cabin, set back from the front.
  const cabin = new THREE.Mesh(new THREE.BoxGeometry(1.1, 0.45, 1.0), darkMat);
  cabin.position.set(0, 0.72, -0.25);
  group.add(cabin);

  // Front marker (arrow head) so heading is unambiguous; points to +Z (front).
  const nose = new THREE.Mesh(new THREE.ConeGeometry(0.28, 0.6, 4), frontMat);
  nose.rotation.x = Math.PI / 2; // cone points up by default -> rotate to +Z
  nose.position.set(0, 0.4, 1.35);
  group.add(nose);

  // Wheels (cylinders) at the four corners, axis along X.
  const wheelGeo = new THREE.CylinderGeometry(0.32, 0.32, 0.22, 20);
  const wheelMat = new THREE.MeshStandardMaterial({
    color: 0x111827,
    metalness: 0.1,
    roughness: 0.9,
  });
  const wheelPositions: [number, number, number][] = [
    [0.75, 0.32, 0.75],
    [-0.75, 0.32, 0.75],
    [0.75, 0.32, -0.75],
    [-0.75, 0.32, -0.75],
  ];
  for (const [x, y, z] of wheelPositions) {
    const wheel = new THREE.Mesh(wheelGeo, wheelMat);
    wheel.rotation.z = Math.PI / 2;
    wheel.position.set(x, y, z);
    group.add(wheel);
  }

  return group;
}

export default function ImuVisualizer({
  roll,
  pitch,
  yaw,
  available,
}: ImuVisualizerProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  // Latest angles, read inside the animation loop without re-running setup.
  const anglesRef = useRef({ roll, pitch, yaw, available });
  const zeroRef = useRef<THREE.Quaternion>(new THREE.Quaternion());
  const robotRef = useRef<THREE.Group | null>(null);
  const [hasZero, setHasZero] = useState(false);

  anglesRef.current = { roll, pitch, yaw, available };

  // One-time scene setup.
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    // Restore a previously saved level reference.
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
    const height = 220;

    const scene = new THREE.Scene();

    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
    camera.position.set(3.6, 2.8, 4.4);
    camera.lookAt(0, 0.4, 0);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height);
    mount.appendChild(renderer.domElement);

    // Lighting.
    scene.add(new THREE.HemisphereLight(0xffffff, 0x404050, 1.1));
    const dir = new THREE.DirectionalLight(0xffffff, 1.2);
    dir.position.set(5, 8, 6);
    scene.add(dir);

    // Ground grid + axes for spatial reference.
    const grid = new THREE.GridHelper(10, 20, 0x0891b2, 0x334155);
    (grid.material as THREE.Material).opacity = 0.35;
    (grid.material as THREE.Material).transparent = true;
    scene.add(grid);

    const axes = new THREE.AxesHelper(1.6);
    axes.position.y = 0.01;
    scene.add(axes);

    const robot = buildRobot();
    robotRef.current = robot;
    scene.add(robot);

    // Smoothly track the target orientation.
    const target = new THREE.Quaternion();
    let frameId = 0;
    const animate = () => {
      const { roll: r, pitch: p, yaw: y } = anglesRef.current;
      const current = quatFromEuler(r, p, y);
      // Displayed orientation is relative to the captured "level" reference, so
      // the robot's real mounting offset (e.g. roll ~180° when flat) is removed.
      target.copy(zeroRef.current).invert().multiply(current);
      robot.quaternion.slerp(target, 0.2);
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
      robotRef.current = null;
    };
  }, []);

  const setLevel = () => {
    const { roll: r, pitch: p, yaw: y } = anglesRef.current;
    zeroRef.current.copy(quatFromEuler(r, p, y));
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

  return (
    <div className="space-y-2">
      <div
        ref={mountRef}
        className="relative w-full overflow-hidden rounded-md bg-gradient-to-b from-slate-100 to-slate-200 dark:from-slate-900 dark:to-slate-950"
        style={{ height: 220 }}
      >
        {!available && (
          <div className="absolute inset-0 flex items-center justify-center bg-background/60 text-xs font-medium text-muted-foreground">
            IMU unavailable
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
