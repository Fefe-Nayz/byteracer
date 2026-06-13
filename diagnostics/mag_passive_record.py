import asyncio
import csv
import json
import math
import os
import time
from pathlib import Path

import websockets

WS_URL = "ws://127.0.0.1:3001/ws"


def msg(name, data=None):
    return json.dumps({"name": name, "data": data or {}, "createdAt": int(time.time() * 1000)})


def get_nested(data, path, default=None):
    cur = data
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def norm(a):
    return (a + 180) % 360 - 180


async def main():
    duration = float(os.environ.get("DURATION", "30"))
    output = Path(f"/tmp/mag_passive_{time.strftime('%Y%m%d_%H%M%S')}.csv")
    rows = []

    async with websockets.connect(WS_URL) as ws:
        await ws.send(msg("client_register", {"type": "controller", "id": "codex-mag-passive"}))
        await ws.send(msg("robot_command", {"command": "simulate_circuit_reset_heading"}))
        started = time.monotonic()
        print(f"RECORDING for {duration:.0f}s ... rotate the robot by hand now")
        while time.monotonic() - started < duration:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            event = json.loads(raw)
            if event.get("name") != "sensor_data":
                continue
            imu = (event.get("data") or {}).get("imu") or {}
            rows.append({
                "t": round(time.monotonic() - started, 3),
                "gyroYaw": imu.get("gyroYaw"),
                "magHeading": imu.get("magHeading"),
                "magAutoReady": imu.get("magAutoReady"),
                "magAutoOffsetX": get_nested(imu, "magAutoOffset.x"),
                "magAutoOffsetY": get_nested(imu, "magAutoOffset.y"),
                "roll": get_nested(imu, "angles.roll"),
                "pitch": get_nested(imu, "angles.pitch"),
                "magX": get_nested(imu, "mag.x"),
                "magY": get_nested(imu, "mag.y"),
                "magZ": get_nested(imu, "mag.z"),
            })

    with output.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["t"])
        w.writeheader()
        w.writerows(rows)

    def span(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return (min(vals), max(vals), max(vals) - min(vals)) if vals else (None, None, None)

    gy = span("gyroYaw")
    mh = span("magHeading")
    mxs = [r["magX"] for r in rows if r.get("magX") is not None]
    mys = [r["magY"] for r in rows if r.get("magY") is not None]
    print(f"CSV={output} ROWS={len(rows)}")
    print(f"gyroYaw   span {gy[2]}  (min {gy[0]} max {gy[1]})")
    print(f"magHeading span {mh[2]}  (min {mh[0]} max {mh[1]})  <-- should be ~360 for a full turn")
    if mxs and mys:
        print(f"magX raw  min {min(mxs):.1f} max {max(mxs):.1f}  center {(min(mxs)+max(mxs))/2:.1f}")
        print(f"magY raw  min {min(mys):.1f} max {max(mys):.1f}  center {(min(mys)+max(mys))/2:.1f}")
    # crude monotonic-tracking check: how well magHeading follows gyroYaw
    pairs = [(r["gyroYaw"], r["magHeading"]) for r in rows if r.get("gyroYaw") is not None and r.get("magHeading") is not None]
    if len(pairs) > 5:
        diffs = [norm(m - g) for g, m in pairs]
        print(f"mag-gyro offset: mean {sum(diffs)/len(diffs):.1f}  spread {max(diffs)-min(diffs):.1f} (low spread = mag tracks gyro)")


if __name__ == "__main__":
    asyncio.run(main())
