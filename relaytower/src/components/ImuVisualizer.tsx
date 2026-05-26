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

interface ImuVisualizerProps {
  quaternion?: Quat;
  available: boolean;
}

const ZERO_STORAGE_KEY = "byteracer-imu-zero-quat";

// Build the little robot car in the IMU body frame: X = forward (nose), Y = left,
// Z = up. The whole model is later tipped by a pivot so this Z-up frame is shown
// in three.js's Y-up world.
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
  const wheelMat = new THREE.MeshStandardMaterial({
    color: 0x111827,
    metalness: 0.1,
    roughness: 0.9,
  });

  // Chassis: length along X (forward), width along Y, height along Z.
  const chassis = new THREE.Mesh(new THREE.BoxGeometry(2.2, 1.4, 0.4), bodyMat);
  chassis.position.z = 0.35;
  group.add(chassis);

  // Cabin, set back toward the rear (-X).
  const cabin = new THREE.Mesh(new THREE.BoxGeometry(1.0, 1.1, 0.45), darkMat);
  cabin.position.set(-0.25, 0, 0.72);
  group.add(cabin);

  // Front marker (arrow) pointing to +X so heading is unambiguous.
  const nose = new THREE.Mesh(new THREE.ConeGeometry(0.28, 0.6, 4), frontMat);
  nose.rotation.z = -Math.PI / 2; // cone points +Y by default -> rotate to +X
  nose.position.set(1.35, 0, 0.4);
  group.add(nose);

  // Wheels: cylinders with their axle along Y (the lateral axis).
  const wheelGeo = new THREE.CylinderGeometry(0.32, 0.32, 0.22, 20);
  const wheelPositions: [number, number, number][] = [
    [0.75, 0.75, 0.32],
    [0.75, -0.75, 0.32],
    [-0.75, 0.75, 0.32],
    [-0.75, -0.75, 0.32],
  ];
  for (const [x, y, z] of wheelPositions) {
    const wheel = new THREE.Mesh(wheelGeo, wheelMat);
    wheel.position.set(x, y, z);
    group.add(wheel);
  }

  return group;
}

export default function ImuVisualizer({
  quaternion,
  available,
}: ImuVisualizerProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  // Latest orientation, read inside the animation loop without re-running setup.
  const quatRef = useRef<Quat>({ w: 1, x: 0, y: 0, z: 0 });
  const availableRef = useRef(available);
  const zeroRef = useRef<THREE.Quaternion>(new THREE.Quaternion());
  const [hasZero, setHasZero] = useState(false);

  if (quaternion) quatRef.current = quaternion;
  availableRef.current = available;

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

    // Ground grid in the three.js Y-up world.
    const grid = new THREE.GridHelper(12, 24, 0x0891b2, 0x334155);
    (grid.material as THREE.Material).opacity = 0.35;
    (grid.material as THREE.Material).transparent = true;
    scene.add(grid);

    // Pivot tips the body Z-up frame into the scene Y-up frame for viewing.
    const pivot = new THREE.Group();
    pivot.rotation.x = -Math.PI / 2;
    scene.add(pivot);

    const robot = buildRobot();
    pivot.add(robot);

    const qCurrent = new THREE.Quaternion();
    const qDisplay = new THREE.Quaternion();
    const qZeroInv = new THREE.Quaternion();

    let frameId = 0;
    const animate = () => {
      const q = quatRef.current;
      qCurrent.set(q.x, q.y, q.z, q.w);
      // Show orientation relative to the captured "level" reference, which
      // cancels the robot's mounting offset (e.g. roll ~180 deg when flat).
      qZeroInv.copy(zeroRef.current).invert();
      qDisplay.copy(qZeroInv).multiply(qCurrent);
      // Smooth toward the target; slerp avoids any wrap/gimbal artifacts.
      robot.quaternion.slerp(qDisplay, 0.25);
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
