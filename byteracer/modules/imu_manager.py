import asyncio
import logging
import math
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class IMUManager:
    """MPU6050-compatible inertial sensor reader with short-term yaw tracking."""

    PWR_MGMT_1 = 0x6B
    SMPLRT_DIV = 0x19
    CONFIG = 0x1A
    GYRO_CONFIG = 0x1B
    ACCEL_CONFIG = 0x1C
    ACCEL_XOUT_H = 0x3B

    ACCEL_SCALE = 16384.0
    GYRO_SCALE = 131.0

    def __init__(self, config_manager=None):
        self.config_manager = config_manager
        config = self._read_config()

        self.enabled = bool(config.get("enabled", True))
        self.bus_id = int(config.get("bus", 1))
        self.address = self._parse_address(config.get("i2c_address", "0x68"))
        self.sample_rate_hz = self._clamp_float(config.get("sample_rate_hz", 50), 5, 100)
        self.calibration_samples = int(self._clamp_float(config.get("calibration_samples", 120), 10, 500))
        self.gyro_deadband_dps = self._clamp_float(config.get("gyro_deadband_dps", 0.35), 0, 5)

        self._bus = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._lock = threading.Lock()

        self.available = False
        self.calibrated = False
        self.error: Optional[str] = None
        self.last_update = 0.0
        self._last_sample_time: Optional[float] = None

        self.gyro_bias = {"x": 0.0, "y": 0.0, "z": 0.0}
        self.accel = {"x": 0.0, "y": 0.0, "z": 0.0}
        self.gyro = {"x": 0.0, "y": 0.0, "z": 0.0}
        self.angles = {"roll": 0.0, "pitch": 0.0, "yaw": 0.0}
        self.temperature_c = 0.0
        self.heading_reference_deg = 0.0

    def _read_config(self) -> Dict[str, Any]:
        if not self.config_manager:
            return {}
        return self.config_manager.get("imu") or {}

    @staticmethod
    def _parse_address(value) -> int:
        if isinstance(value, int):
            return value
        try:
            return int(str(value), 0)
        except (TypeError, ValueError):
            return 0x68

    @staticmethod
    def _clamp_float(value, low, high) -> float:
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = low
        return max(low, min(high, value))

    @staticmethod
    def _normalize_angle(angle: float) -> float:
        return (angle + 180.0) % 360.0 - 180.0

    async def start(self):
        if self._running:
            return

        self._running = True
        if not self.enabled:
            logger.info("IMU disabled by configuration")
            return

        try:
            await asyncio.to_thread(self._initialize_sensor)
        except Exception as exc:
            self.available = False
            self.error = str(exc)
            if self._bus:
                try:
                    close = getattr(self._bus, "close", None)
                    if close:
                        close()
                except Exception:
                    pass
                self._bus = None
            logger.warning("IMU initialization failed: %s", exc)
            return

        self._task = asyncio.create_task(self._sample_loop())

    async def stop(self):
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._bus:
            try:
                close = getattr(self._bus, "close", None)
                if close:
                    close()
            except Exception as exc:
                logger.debug("Error closing IMU bus: %s", exc)
            self._bus = None

        self.available = False

    async def configure(self, config: Dict[str, Any]):
        was_enabled = self.enabled
        was_running = self._running
        old_bus_id = self.bus_id
        old_address = self.address

        self.enabled = bool(config.get("enabled", self.enabled))
        self.bus_id = int(config.get("bus", self.bus_id))
        self.address = self._parse_address(config.get("i2c_address", self.address))
        self.sample_rate_hz = self._clamp_float(config.get("sample_rate_hz", self.sample_rate_hz), 5, 100)
        self.calibration_samples = int(self._clamp_float(config.get("calibration_samples", self.calibration_samples), 10, 500))
        self.gyro_deadband_dps = self._clamp_float(config.get("gyro_deadband_dps", self.gyro_deadband_dps), 0, 5)

        if not was_running:
            if self.enabled:
                await self.start()
            return

        if not self.enabled:
            await self.stop()
            return

        if not was_enabled or not self.available or old_bus_id != self.bus_id or old_address != self.address:
            await self.stop()
            self._running = False
            await self.start()

    def _initialize_sensor(self):
        try:
            from smbus2 import SMBus
        except ImportError:
            try:
                from smbus import SMBus
            except ImportError as exc:
                raise RuntimeError("smbus2/smbus is not installed") from exc

        self._bus = SMBus(self.bus_id)
        self._bus.write_byte_data(self.address, self.PWR_MGMT_1, 0x00)
        time.sleep(0.05)
        self._bus.write_byte_data(self.address, self.CONFIG, 0x03)
        self._bus.write_byte_data(self.address, self.GYRO_CONFIG, 0x00)
        self._bus.write_byte_data(self.address, self.ACCEL_CONFIG, 0x00)
        divider = max(0, min(255, int((1000 / self.sample_rate_hz) - 1)))
        self._bus.write_byte_data(self.address, self.SMPLRT_DIV, divider)

        self._calibrate_gyro()
        self.available = True
        self.error = None
        self._last_sample_time = None
        logger.info("IMU initialized on I2C bus %s address 0x%02x", self.bus_id, self.address)

    def _calibrate_gyro(self):
        sums = {"x": 0.0, "y": 0.0, "z": 0.0}
        samples = 0

        for _ in range(self.calibration_samples):
            raw = self._read_raw_values()
            gyro = raw["gyro"]
            sums["x"] += gyro["x"] / self.GYRO_SCALE
            sums["y"] += gyro["y"] / self.GYRO_SCALE
            sums["z"] += gyro["z"] / self.GYRO_SCALE
            samples += 1
            time.sleep(0.004)

        if samples:
            self.gyro_bias = {axis: sums[axis] / samples for axis in sums}
        self.calibrated = True
        logger.info("IMU gyro bias calibrated: %s", self.gyro_bias)

    async def _sample_loop(self):
        period = 1.0 / max(1.0, self.sample_rate_hz)

        while self._running and self.enabled:
            started = time.monotonic()
            try:
                raw = await asyncio.to_thread(self._read_raw_values)
                self._update_state(raw)
                self.available = True
                self.error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.available = False
                self.error = str(exc)
                logger.debug("IMU sample failed: %s", exc)

            elapsed = time.monotonic() - started
            await asyncio.sleep(max(0.0, period - elapsed))

    def _read_raw_values(self) -> Dict[str, Dict[str, float] | float]:
        if self._bus is None:
            raise RuntimeError("IMU bus is not initialized")

        data = self._bus.read_i2c_block_data(self.address, self.ACCEL_XOUT_H, 14)

        def word(index: int) -> int:
            value = (data[index] << 8) | data[index + 1]
            return value - 65536 if value & 0x8000 else value

        return {
            "accel": {"x": word(0), "y": word(2), "z": word(4)},
            "temperature_raw": word(6),
            "gyro": {"x": word(8), "y": word(10), "z": word(12)},
        }

    def _update_state(self, raw: Dict[str, Any]):
        now = time.monotonic()
        if self._last_sample_time is None:
            dt = 0.0
        else:
            dt = min(0.2, max(0.0, now - self._last_sample_time))
        self._last_sample_time = now

        accel = {axis: raw["accel"][axis] / self.ACCEL_SCALE for axis in ("x", "y", "z")}
        gyro = {}
        for axis in ("x", "y", "z"):
            value = raw["gyro"][axis] / self.GYRO_SCALE - self.gyro_bias.get(axis, 0.0)
            if abs(value) < self.gyro_deadband_dps:
                value = 0.0
            gyro[axis] = value

        roll_acc = math.degrees(math.atan2(accel["y"], accel["z"]))
        pitch_acc = math.degrees(math.atan2(-accel["x"], math.sqrt(accel["y"] ** 2 + accel["z"] ** 2)))

        with self._lock:
            alpha = 0.96
            if dt <= 0:
                roll = roll_acc
                pitch = pitch_acc
            else:
                roll = alpha * (self.angles["roll"] + gyro["x"] * dt) + (1 - alpha) * roll_acc
                pitch = alpha * (self.angles["pitch"] + gyro["y"] * dt) + (1 - alpha) * pitch_acc

            yaw = self._normalize_angle(self.angles["yaw"] + gyro["z"] * dt)

            self.accel = accel
            self.gyro = gyro
            self.temperature_c = raw["temperature_raw"] / 340.0 + 36.53
            self.angles = {"roll": roll, "pitch": pitch, "yaw": yaw}
            self.last_update = time.time()

    def is_ready(self) -> bool:
        return bool(self.enabled and self.available and self.calibrated)

    def reset_heading_reference(self):
        with self._lock:
            self.heading_reference_deg = self.angles["yaw"]
        logger.info("IMU heading reference reset to %.2f degrees", self.heading_reference_deg)

    def get_heading_error_deg(self) -> float:
        with self._lock:
            return self._normalize_angle(self.angles["yaw"] - self.heading_reference_deg)

    def angle_delta_from(self, start_yaw: float) -> float:
        with self._lock:
            return self._normalize_angle(self.angles["yaw"] - start_yaw)

    def get_yaw_deg(self) -> float:
        with self._lock:
            return float(self.angles["yaw"])

    def get_data(self) -> Dict[str, Any]:
        with self._lock:
            heading_error = self._normalize_angle(self.angles["yaw"] - self.heading_reference_deg)
            return {
                "enabled": self.enabled,
                "available": self.available,
                "calibrated": self.calibrated,
                "bus": self.bus_id,
                "address": f"0x{self.address:02x}",
                "accel": dict(self.accel),
                "gyro": dict(self.gyro),
                "angles": dict(self.angles),
                "heading": self.angles["yaw"],
                "headingReference": self.heading_reference_deg,
                "headingError": heading_error,
                "temperature": self.temperature_c,
                "lastUpdated": int(self.last_update * 1000) if self.last_update else None,
                "error": self.error,
            }
