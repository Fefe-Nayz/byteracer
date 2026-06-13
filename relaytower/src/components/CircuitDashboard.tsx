"use client";

import { useEffect, useRef, useState } from "react";
import { Card } from "./ui/card";
import { Button } from "./ui/button";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { Activity, Cpu, Gauge, Compass, Route, Timer } from "lucide-react";

const HISTORY_LEN = 240; // ~12 s at 20 Hz telemetry

interface Series {
  yaw: number[];
  ref: number[];
  err: number[];
  steer: number[];
  rate: number[];
  t: number[];
}

interface SparklineProps {
  series: number[];
  width?: number;
  height?: number;
  color: string;
  baseline?: number; // draw a horizontal guide at this y-value
  min?: number;
  max?: number;
}

// Hand-rolled SVG sparkline so we don't pull in a charting library just to
// draw three time-series. Auto-ranges if min/max aren't provided.
function Sparkline({
  series,
  width = 240,
  height = 56,
  color,
  baseline,
  min,
  max,
}: SparklineProps) {
  if (series.length === 0) {
    return <svg width={width} height={height} />;
  }
  const lo = min !== undefined ? min : Math.min(...series);
  const hi = max !== undefined ? max : Math.max(...series);
  const range = hi - lo || 1;
  const dx = width / Math.max(1, series.length - 1);
  const pts = series
    .map((v, i) => {
      const x = i * dx;
      const y = height - ((v - lo) / range) * (height - 4) - 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  let baselineY: number | null = null;
  if (baseline !== undefined && baseline >= lo && baseline <= hi) {
    baselineY = height - ((baseline - lo) / range) * (height - 4) - 2;
  }

  return (
    <svg width={width} height={height} className="block w-full">
      <rect x={0} y={0} width={width} height={height} className="fill-muted/40" />
      {baselineY !== null && (
        <line
          x1={0}
          x2={width}
          y1={baselineY}
          y2={baselineY}
          className="stroke-foreground/30"
          strokeDasharray="2 3"
          strokeWidth={1}
        />
      )}
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

interface StatProps {
  label: string;
  value: string;
  unit?: string;
  tone?: "default" | "good" | "warn" | "muted";
  hint?: string;
}

function Stat({ label, value, unit, tone = "default", hint }: StatProps) {
  const toneCls =
    tone === "good"
      ? "text-emerald-600 dark:text-emerald-400"
      : tone === "warn"
      ? "text-amber-600 dark:text-amber-400"
      : tone === "muted"
      ? "text-muted-foreground"
      : "";
  return (
    <div className="rounded-md bg-muted/50 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className={`text-sm font-semibold tabular-nums ${toneCls}`}>
        {value}
        {unit && <span className="ml-0.5 text-[10px] font-normal">{unit}</span>}
      </div>
      {hint && (
        <div className="text-[9px] text-muted-foreground">{hint}</div>
      )}
    </div>
  );
}

function fmt(value: number | undefined | null, digits = 1) {
  if (value === undefined || value === null || Number.isNaN(value)) return "–";
  return value.toFixed(digits);
}

export default function CircuitDashboard() {
  const { sensorData, settings, sendRobotCommand } = useWebSocket();
  const circuitModeOn = !!settings?.modes?.circuit_mode_enabled;
  const circuit = sensorData?.circuit;
  const noInference = !!settings?.ai?.circuit_no_inference;

  const seriesRef = useRef<Series>({
    yaw: [],
    ref: [],
    err: [],
    steer: [],
    rate: [],
    t: [],
  });
  // Tick state forces a re-render after each telemetry update without
  // re-allocating the ring buffer.
  const [, setTick] = useState(0);
  const lastPushRef = useRef(0);

  useEffect(() => {
    if (!circuit) return;
    const now = performance.now();
    // Cap UI update rate at ~25 Hz regardless of how often telemetry arrives.
    if (now - lastPushRef.current < 40) return;
    lastPushRef.current = now;

    const s = seriesRef.current;
    const push = (arr: number[], v: number) => {
      arr.push(v);
      if (arr.length > HISTORY_LEN) arr.shift();
    };
    push(s.yaw, circuit.currentHeading ?? 0);
    push(s.ref, circuit.headingReference ?? 0);
    push(s.err, circuit.headingError ?? 0);
    push(s.steer, circuit.steeringCommand ?? 0);
    push(s.rate, circuit.gyroRateZ ?? 0);
    push(s.t, now);
    setTick((n) => n + 1);
  }, [
    circuit?.currentHeading,
    circuit?.headingReference,
    circuit?.headingError,
    circuit?.steeringCommand,
    circuit?.gyroRateZ,
    circuit,
  ]);

  if (!circuitModeOn) return null;

  const s = seriesRef.current;
  const ctrlFps = circuit?.controlFps ?? 0;
  const yoloFps = circuit?.yoloFps ?? 0;
  const infMs = circuit?.yoloInferenceMs ?? 0;
  const loopMs = circuit?.controlLoopMs ?? 0;
  const ctrlTone =
    ctrlFps > 15 ? "good" : ctrlFps > 8 ? "warn" : ctrlFps > 0 ? "warn" : "muted";

  // Heading-error tolerance bands for visual guidance.
  const errAbs = Math.abs(circuit?.headingError ?? 0);

  // Compose y-axis bounds for the steering chart against the configured max.
  const maxSteer = circuit?.maxSteeringDeg || 30;
  const hasTurnCompass =
    circuit?.turnStartMagHeading !== undefined ||
    circuit?.turnTargetMagHeading !== undefined ||
    circuit?.turnFinalMagHeading !== undefined ||
    circuit?.turnMagDelta !== undefined ||
    circuit?.turnMagError !== undefined ||
    circuit?.turnAppliedMagError !== undefined;

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center gap-2">
        <Route className="h-5 w-5 text-cyan-600 dark:text-cyan-400" />
        <h3 className="text-sm font-semibold">Circuit Mode Dashboard</h3>
        <span
          className={`ml-auto rounded px-1.5 py-0.5 text-[10px] font-medium ${
            circuit?.imuActive
              ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
              : "bg-amber-500/15 text-amber-700 dark:text-amber-300"
          }`}
        >
          {circuit?.imuActive
            ? "IMU hold active"
            : circuit?.enabled
            ? "IMU hold idle"
            : "IMU disabled"}
        </span>
        {circuit?.turnActive && (
          <span className="rounded bg-orange-500/15 px-1.5 py-0.5 text-[10px] font-medium text-orange-700 dark:text-orange-300">
            TURNING
          </span>
        )}
      </div>

      {/* Performance counters */}
      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat
          label="Control loop"
          value={fmt(ctrlFps, 1)}
          unit="Hz"
          tone={ctrlTone}
          hint={`${fmt(loopMs, 1)} ms / iter`}
        />
        <Stat
          label="YOLO"
          value={fmt(yoloFps, 1)}
          unit="Hz"
          tone={yoloFps > 4 ? "good" : "muted"}
          hint={`${fmt(infMs, 0)} ms infer`}
        />
        <Stat
          label="Detected"
          value={`${circuit?.yoloObjects ?? 0}`}
          unit="obj"
          tone="muted"
        />
        <Stat
          label="Drive"
          value={fmt((circuit?.driveSpeed ?? 0) * 100, 0)}
          unit="%"
          tone={(circuit?.driveSpeed ?? 0) > 0 ? "good" : "muted"}
        />
      </div>

      {noInference && (
        <div className="mb-3 rounded-md border border-cyan-500/25 bg-cyan-500/5 p-2">
          <div className="mb-2 flex items-center justify-between gap-2">
            <div>
              <div className="text-xs font-medium text-cyan-700 dark:text-cyan-300">
                Simulation controls
              </div>
              <div className="text-[10px] text-muted-foreground">
                YOLO is bypassed; these buttons inject the real circuit handlers.
              </div>
            </div>
            <span className="rounded bg-cyan-500/15 px-1.5 py-0.5 text-[10px] font-medium text-cyan-700 dark:text-cyan-300">
              NO INFERENCE
            </span>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Button size="sm" variant="outline" onClick={() => sendRobotCommand("simulate_circuit_green_light")}>
              Green
            </Button>
            <Button size="sm" variant="outline" onClick={() => sendRobotCommand("simulate_circuit_red_light")}>
              Red
            </Button>
            <Button size="sm" variant="outline" onClick={() => sendRobotCommand("simulate_circuit_stop_sign")}>
              Stop
            </Button>
            <Button size="sm" variant="outline" onClick={() => sendRobotCommand("simulate_circuit_right_turn")}>
              Turn
            </Button>
            <Button size="sm" variant="secondary" onClick={() => sendRobotCommand("simulate_circuit_resume")}>
              Resume
            </Button>
            <Button size="sm" variant="secondary" onClick={() => sendRobotCommand("simulate_circuit_reset_heading")}>
              Reset heading
            </Button>
            <Button size="sm" variant="secondary" onClick={() => sendRobotCommand("simulate_circuit_stop_motion")}>
              Pause
            </Button>
          </div>
        </div>
      )}

      {/* Heading state */}
      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat
          label="Heading target"
          value={`${fmt(circuit?.headingReference, 1)}°`}
        />
        <Stat
          label="Heading current"
          value={`${fmt(circuit?.currentHeading, 1)}°`}
        />
        <Stat
          label="Error"
          value={`${fmt(circuit?.headingError, 1)}°`}
          tone={errAbs < 2 ? "good" : errAbs < 8 ? "warn" : "muted"}
        />
        <Stat
          label="Steering"
          value={`${fmt(circuit?.steeringCommand, 1)}°`}
          hint={`max ${fmt(maxSteer, 0)}°`}
        />
      </div>

      <div className="mb-3 grid grid-cols-3 gap-2">
        <Stat
          label="Motor diff"
          value={fmt((circuit?.motorDifferential ?? 0) * 100, 1)}
          unit="%"
          tone={Math.abs(circuit?.motorDifferential ?? 0) > 0.01 ? "warn" : "muted"}
        />
        <Stat
          label="Left motor"
          value={fmt((circuit?.leftMotorCommand ?? 0) * 100, 0)}
          unit="%"
          tone={(circuit?.leftMotorCommand ?? 0) > 0 ? "good" : "muted"}
        />
        <Stat
          label="Right motor"
          value={fmt((circuit?.rightMotorCommand ?? 0) * 100, 0)}
          unit="%"
          tone={(circuit?.rightMotorCommand ?? 0) > 0 ? "good" : "muted"}
        />
      </div>

      {/* Turn progress */}
      {circuit?.turnActive && (
        <div className="mb-3 rounded-md border border-orange-500/30 bg-orange-500/5 p-2">
          <div className="mb-1 flex items-center justify-between text-xs">
            <span className="font-medium text-orange-700 dark:text-orange-300">
              Turn in progress
              {circuit.turnInPlace ? " (in place)" : " (arc)"}
            </span>
            <span className="tabular-nums">
              {fmt(circuit.turnCurrentDelta, 0)}° / {fmt(circuit.turnTargetDeg, 0)}°
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded bg-muted">
            <div
              className="h-full bg-orange-500 transition-[width] duration-100"
              style={{
                width: `${Math.min(
                  100,
                  (circuit.turnCurrentDelta / Math.max(1, circuit.turnTargetDeg)) * 100
                )}%`,
              }}
            />
          </div>
        </div>
      )}

      {hasTurnCompass && (
        <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-6">
          <Stat
            label="Turn ref"
            value={
              circuit?.turnReferenceSource === "magnetometer"
                ? "Compass"
                : circuit?.turnReferenceSource === "magnetometer-clamped"
                ? "Clamped"
                : "Gyro"
            }
            tone={
              circuit?.turnReferenceSource === "magnetometer"
                ? "good"
                : circuit?.turnReferenceSource === "magnetometer-clamped"
                ? "warn"
                : "muted"
            }
          />
          <Stat label="Mag start" value={`${fmt(circuit?.turnStartMagHeading, 1)}°`} />
          <Stat label="Mag target" value={`${fmt(circuit?.turnTargetMagHeading, 1)}°`} />
          <Stat label="Mag final" value={`${fmt(circuit?.turnFinalMagHeading, 1)}°`} />
          <Stat
            label="Mag error"
            value={`${fmt(circuit?.turnAppliedMagError ?? circuit?.turnMagError, 1)}°`}
            hint={
              circuit?.turnAppliedMagError !== undefined && circuit?.turnAppliedMagError !== circuit?.turnMagError
                ? `raw ${fmt(circuit?.turnMagError, 1)}°`
                : undefined
            }
            tone={Math.abs((circuit?.turnAppliedMagError ?? circuit?.turnMagError) ?? 0) < 5 ? "good" : "warn"}
          />
          <Stat
            label="Mag/gyro diff"
            value={`${fmt(circuit?.turnMagAgreementError, 1)}°`}
            tone={Math.abs(circuit?.turnMagAgreementError ?? 0) < 15 ? "good" : "warn"}
          />
        </div>
      )}

      {/* Time series charts */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <div>
          <div className="mb-1 flex items-center justify-between text-[11px]">
            <span className="flex items-center gap-1 text-muted-foreground">
              <Compass className="h-3 w-3" /> Yaw vs target
            </span>
            <span className="tabular-nums">
              <span className="text-cyan-600 dark:text-cyan-400">
                {fmt(circuit?.currentHeading, 1)}°
              </span>{" "}
              /{" "}
              <span className="text-muted-foreground">
                {fmt(circuit?.headingReference, 1)}°
              </span>
            </span>
          </div>
          <div className="relative">
            <Sparkline series={s.yaw} color="rgb(8 145 178)" />
            <div className="absolute inset-0 pointer-events-none">
              <Sparkline series={s.ref} color="rgb(148 163 184)" />
            </div>
          </div>
        </div>
        <div>
          <div className="mb-1 flex items-center justify-between text-[11px]">
            <span className="flex items-center gap-1 text-muted-foreground">
              <Activity className="h-3 w-3" /> Heading error
            </span>
            <span className="tabular-nums">{fmt(circuit?.headingError, 1)}°</span>
          </div>
          <Sparkline series={s.err} color="rgb(217 119 6)" baseline={0} />
        </div>
        <div>
          <div className="mb-1 flex items-center justify-between text-[11px]">
            <span className="flex items-center gap-1 text-muted-foreground">
              <Gauge className="h-3 w-3" /> Steering cmd
            </span>
            <span className="tabular-nums">
              {fmt(circuit?.steeringCommand, 1)}°
            </span>
          </div>
          <Sparkline
            series={s.steer}
            color="rgb(59 130 246)"
            baseline={0}
            min={-maxSteer}
            max={maxSteer}
          />
        </div>
      </div>

      {/* Gyro Z over time, full width */}
      <div className="mt-3">
        <div className="mb-1 flex items-center justify-between text-[11px]">
          <span className="flex items-center gap-1 text-muted-foreground">
            <Timer className="h-3 w-3" /> Yaw rate (gyro Z)
          </span>
          <span className="tabular-nums">{fmt(circuit?.gyroRateZ, 1)} °/s</span>
        </div>
        <Sparkline
          series={s.rate}
          color="rgb(168 85 247)"
          baseline={0}
          height={48}
        />
      </div>

      <div className="mt-3 flex items-center gap-2 text-[10px] text-muted-foreground">
        <Cpu className="h-3 w-3" />
        <span>
          Control loop is pinned to real-time priority; YOLO inference is niced
          down so the heading hold keeps its rate even at 100% CPU.
        </span>
      </div>
    </Card>
  );
}
