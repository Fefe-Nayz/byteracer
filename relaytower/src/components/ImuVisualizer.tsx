"use client";

import { CSSProperties } from "react";

interface ImuVisualizerProps {
  roll: number;
  pitch: number;
  yaw: number;
  available: boolean;
}

// Box half/full dimensions in px (X = width, Y = height, Z = length/forward).
const W = 78; // left-right width
const H = 26; // vertical height
const L = 128; // front-back length

// A single face of the chassis box. Each face is positioned in 3D by rotating
// it into place and pushing it out by half of the box's extent on that axis.
function Face({
  width,
  height,
  transform,
  className,
  children,
}: {
  width: number;
  height: number;
  transform: string;
  className: string;
  children?: React.ReactNode;
}) {
  const style: CSSProperties = {
    position: "absolute",
    width: `${width}px`,
    height: `${height}px`,
    left: "50%",
    top: "50%",
    marginLeft: `${-width / 2}px`,
    marginTop: `${-height / 2}px`,
    transform,
    backfaceVisibility: "hidden",
  };
  return (
    <div style={style} className={className}>
      {children}
    </div>
  );
}

export default function ImuVisualizer({
  roll,
  pitch,
  yaw,
  available,
}: ImuVisualizerProps) {
  // Map the IMU euler angles onto CSS rotations:
  //   yaw   -> rotateY (heading, about the vertical axis)
  //   pitch -> rotateX (nose up / down)
  //   roll  -> rotateZ (banking left / right)
  // Signs are chosen so the model leans the same way as the robot; flip a sign
  // here if a test on the real robot shows an axis moving the wrong direction.
  const modelTransform = available
    ? `rotateY(${yaw}deg) rotateX(${-pitch}deg) rotateZ(${roll}deg)`
    : "rotateX(0deg)";

  const faceBase =
    "flex items-center justify-center text-[9px] font-semibold tracking-wide select-none";

  return (
    <div
      className="relative w-full h-40 overflow-hidden rounded-md bg-gradient-to-b from-slate-100 to-slate-200 dark:from-slate-900 dark:to-slate-950"
      style={{ perspective: "620px" }}
    >
      {/* Fixed camera tilt so the chassis reads as 3D even when level. */}
      <div
        className="absolute inset-0 flex items-center justify-center"
        style={{
          transformStyle: "preserve-3d",
          transform: "rotateX(62deg) rotateZ(0deg)",
        }}
      >
        {/* Ground grid for depth perception. */}
        <div
          className="absolute rounded-full opacity-40 dark:opacity-30"
          style={{
            width: "260px",
            height: "260px",
            transform: "translateZ(-1px)",
            backgroundImage:
              "linear-gradient(to right, rgba(6,182,212,0.35) 1px, transparent 1px), linear-gradient(to bottom, rgba(6,182,212,0.35) 1px, transparent 1px)",
            backgroundSize: "26px 26px",
            maskImage: "radial-gradient(circle, black 35%, transparent 72%)",
            WebkitMaskImage:
              "radial-gradient(circle, black 35%, transparent 72%)",
          }}
        />

        {/* The chassis. Rotations are applied here from live IMU angles. */}
        <div
          style={{
            transformStyle: "preserve-3d",
            transform: modelTransform,
            transition: "transform 90ms linear",
          }}
        >
          {/* Front (forward / +Z) */}
          <Face
            width={W}
            height={H}
            transform={`translateZ(${L / 2}px)`}
            className={`${faceBase} text-white bg-cyan-500/85 border border-cyan-300`}
          >
            ▲ FRONT
          </Face>
          {/* Back (-Z) */}
          <Face
            width={W}
            height={H}
            transform={`rotateY(180deg) translateZ(${L / 2}px)`}
            className={`${faceBase} text-cyan-50 bg-cyan-800/80 border border-cyan-600`}
          >
            REAR
          </Face>
          {/* Right (+X) */}
          <Face
            width={L}
            height={H}
            transform={`rotateY(90deg) translateZ(${W / 2}px)`}
            className={`${faceBase} text-cyan-50 bg-cyan-700/75 border border-cyan-500`}
          />
          {/* Left (-X) */}
          <Face
            width={L}
            height={H}
            transform={`rotateY(-90deg) translateZ(${W / 2}px)`}
            className={`${faceBase} text-cyan-50 bg-cyan-700/75 border border-cyan-500`}
          />
          {/* Top (roof) */}
          <Face
            width={W}
            height={L}
            transform={`rotateX(90deg) translateZ(${H / 2}px)`}
            className={`${faceBase} bg-cyan-600/70 border border-cyan-300 text-white`}
          >
            <span style={{ transform: "rotate(180deg)" }}>▲</span>
          </Face>
          {/* Bottom (chassis underside) */}
          <Face
            width={W}
            height={L}
            transform={`rotateX(-90deg) translateZ(${H / 2}px)`}
            className={`${faceBase} bg-slate-600/80 border border-slate-400`}
          />
        </div>
      </div>

      {!available && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/60 text-xs font-medium text-muted-foreground">
          IMU unavailable
        </div>
      )}
    </div>
  );
}
