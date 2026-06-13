import asyncio
import csv
import json
import os
import time
from pathlib import Path

import websockets


WS_URL = "ws://127.0.0.1:3001/ws"


def msg(name, data=None):
    now = int(time.time() * 1000)
    return json.dumps({"name": name, "data": data or {}, "createdAt": now})


def get_nested(data, path, default=None):
    cur = data
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


FIELDS = [
    "t",
    "phase",
    "turnActive",
    "turnCurrentDelta",
    "turnTargetDeg",
    "turnStartYaw",
    "turnStartMagHeading",
    "turnTargetMagHeading",
    "turnFinalMagHeading",
    "turnMagDelta",
    "turnMagError",
    "turnAppliedMagError",
    "turnMagAgreementError",
    "turnReferenceSource",
    "gyroYaw",
    "gyroZ",
    "dtMaxMs",
    "dtCappedCount",
    "sampleCount",
    "roll",
    "pitch",
    "magHeading",
    "magX",
    "magY",
    "magZ",
    "accelX",
    "accelY",
    "accelZ",
    "headingReference",
    "headingError",
    "currentHeading",
    "steeringCommand",
    "motorDifferential",
    "leftMotorCommand",
    "rightMotorCommand",
    "driveSpeed",
]


async def main():
    turns_to_run = max(1, int(os.environ.get("TURNS", "1")))
    output = Path(f"/tmp/right_turn_magnetometer_{time.strftime('%Y%m%d_%H%M%S')}.csv")
    rows = []

    async with websockets.connect(WS_URL) as ws:
        await ws.send(msg("client_register", {"type": "controller", "id": "codex-right-turn-diag"}))
        await ws.send(msg("robot_command", {"command": "simulate_circuit_stop_motion"}))
        await asyncio.sleep(0.3)
        await ws.send(msg("robot_command", {"command": "simulate_circuit_reset_heading"}))
        await asyncio.sleep(1.0)

        for turn_index in range(1, turns_to_run + 1):
            phase = f"before{turn_index}"
            saw_turn = False
            turn_done_at = None
            await ws.send(msg("test_calibration", {"timestamp": int(time.time() * 1000), "turn": turn_index}))
            started_at = time.monotonic()

            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                except asyncio.TimeoutError:
                    if time.monotonic() - started_at > 18:
                        break
                    continue

                event = json.loads(raw)
                if event.get("name") != "sensor_data":
                    continue
                data = event.get("data") or {}
                circuit = data.get("circuit") or {}
                imu = data.get("imu") or {}
                turn_active = bool(circuit.get("turnActive"))

                if turn_active:
                    saw_turn = True
                    phase = f"turn{turn_index}"
                elif saw_turn and turn_done_at is None:
                    turn_done_at = time.monotonic()
                    phase = f"after{turn_index}"
                elif saw_turn:
                    phase = f"after{turn_index}"

                rows.append(
                    {
                        "t": time.time(),
                        "phase": phase,
                        "turnActive": turn_active,
                        "turnCurrentDelta": circuit.get("turnCurrentDelta"),
                        "turnTargetDeg": circuit.get("turnTargetDeg"),
                        "turnStartYaw": circuit.get("turnStartYaw"),
                        "turnStartMagHeading": circuit.get("turnStartMagHeading"),
                        "turnTargetMagHeading": circuit.get("turnTargetMagHeading"),
                        "turnFinalMagHeading": circuit.get("turnFinalMagHeading"),
                        "turnMagDelta": circuit.get("turnMagDelta"),
                        "turnMagError": circuit.get("turnMagError"),
                        "turnAppliedMagError": circuit.get("turnAppliedMagError"),
                        "turnMagAgreementError": circuit.get("turnMagAgreementError"),
                        "turnReferenceSource": circuit.get("turnReferenceSource"),
                        "gyroYaw": imu.get("gyroYaw"),
                        "gyroZ": get_nested(imu, "gyro.z"),
                        "dtMaxMs": imu.get("dtMaxMs"),
                        "dtCappedCount": imu.get("dtCappedCount"),
                        "sampleCount": imu.get("sampleCount"),
                        "roll": get_nested(imu, "angles.roll"),
                        "pitch": get_nested(imu, "angles.pitch"),
                        "magHeading": imu.get("magHeading"),
                        "magX": get_nested(imu, "mag.x"),
                        "magY": get_nested(imu, "magY") or get_nested(imu, "mag.y"),
                        "magZ": get_nested(imu, "mag.z"),
                        "accelX": get_nested(imu, "accel.x"),
                        "accelY": get_nested(imu, "accel.y"),
                        "accelZ": get_nested(imu, "accel.z"),
                        "headingReference": imu.get("headingReference"),
                        "headingError": imu.get("headingError"),
                        "currentHeading": circuit.get("currentHeading"),
                        "steeringCommand": circuit.get("steeringCommand"),
                        "motorDifferential": circuit.get("motorDifferential"),
                        "leftMotorCommand": circuit.get("leftMotorCommand"),
                        "rightMotorCommand": circuit.get("rightMotorCommand"),
                        "driveSpeed": circuit.get("driveSpeed"),
                    }
                )

                if turn_done_at and time.monotonic() - turn_done_at > 1.5:
                    break

            await ws.send(msg("robot_command", {"command": "simulate_circuit_stop_motion"}))
            await asyncio.sleep(0.5)

    with output.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    turn_rows = [r for r in rows if str(r["phase"]).startswith("turn")]
    after_rows = [r for r in rows if str(r["phase"]).startswith("after")]
    last = rows[-1] if rows else {}
    print(f"CSV={output}")
    print(f"ROWS={len(rows)} TURN_ROWS={len(turn_rows)} AFTER_ROWS={len(after_rows)} SAW_TURN={saw_turn}")
    print(
        "SAMPLING "
        f"dtMaxMs={last.get('dtMaxMs')} "
        f"dtCappedCount={last.get('dtCappedCount')} "
        f"sampleCount={last.get('sampleCount')}"
    )
    print(
        "FINAL "
        f"source={last.get('turnReferenceSource')} "
        f"startMag={last.get('turnStartMagHeading')} "
        f"targetMag={last.get('turnTargetMagHeading')} "
        f"finalMag={last.get('turnFinalMagHeading')} "
        f"magDelta={last.get('turnMagDelta')} "
        f"magError={last.get('turnMagError')} "
        f"appliedMagError={last.get('turnAppliedMagError')} "
        f"magAgreement={last.get('turnMagAgreementError')} "
        f"headingError={last.get('headingError')}"
    )


if __name__ == "__main__":
    asyncio.run(main())
