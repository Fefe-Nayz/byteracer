import asyncio
import logging
import math
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class IMUManager:
    """Inertial sensor reader for MPU6050 and MPU9250.

    Both share the same accel/gyro register map. The MPU9250 additionally carries
    an AK8963 magnetometer; when ``sensor_type`` is ``mpu9250`` we read it and fuse
    a tilt-compensated magnetic heading into the yaw estimate, which removes the
    slow gyro drift the MPU6050 suffers from (it has no magnetometer).
    """

    PWR_MGMT_1 = 0x6B
    SMPLRT_DIV = 0x19
    CONFIG = 0x1A
    GYRO_CONFIG = 0x1B
    ACCEL_CONFIG = 0x1C
    ACCEL_XOUT_H = 0x3B
    INT_PIN_CFG = 0x37  # used to enable I2C bypass so the AK8963 is reachable

    ACCEL_SCALE = 16384.0
    GYRO_SCALE = 131.0

    # AK8963 magnetometer (MPU9250 only), reachable on the main bus once bypass
    # mode is enabled.
    AK8963_ADDRESS = 0x0C
    AK8963_WIA = 0x00
    AK8963_ST1 = 0x02
    AK8963_HXL = 0x03
    AK8963_CNTL1 = 0x0A
    AK8963_ASAX = 0x10
    # microtesla per LSB in 16-bit mode: 4912 uT range / 32760
    MAG_SCALE_UT = 4912.0 / 32760.0

    def __init__(self, config_manager=None):
        self.config_manager = config_manager
        config = self._read_config()

        self.enabled = bool(config.get("enabled", True))
        self.sensor_type = self._parse_sensor_type(config.get("sensor_type", "mpu6050"))
        self.bus_id = int(config.get("bus", 1))
        self.address = self._parse_address(config.get("i2c_address", "0x68"))
        self.sample_rate_hz = self._clamp_float(config.get("sample_rate_hz", 50), 5, 100)
        self.calibration_samples = int(self._clamp_float(config.get("calibration_samples", 120), 10, 500))
        self.gyro_deadband_dps = self._clamp_float(config.get("gyro_deadband_dps", 0.35), 0, 5)
        # Magnetometer options (MPU9250 only).
        self.mag_declination_deg = self._clamp_float(config.get("mag_declination_deg", 0.0), -180, 180)
        self.mag_yaw_invert = bool(config.get("mag_yaw_invert", False))

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
        self.mag = {"x": 0.0, "y": 0.0, "z": 0.0}
        self.angles = {"roll": 0.0, "pitch": 0.0, "yaw": 0.0}
        # Pure gyro-integrated yaw, used for short-term closed-loop control
        # (straight-line heading hold and timed turns). Unlike angles["yaw"], it
        # is never pulled by the magnetometer, so motor magnetic interference
        # cannot corrupt it during a powered turn. It drifts slowly over minutes,
        # which is irrelevant for the few-second circuit manoeuvres.
        self.gyro_yaw_deg = 0.0
        # Orientation quaternion sent to the UI for the 3D visualizer. Built from
        # the instantaneous accelerometer tilt + fused yaw, so it stays fluid (no
        # gyro-integration overshoot) and consistent (no Euler axis coupling).
        self.orientation_quat = {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0}
        self.temperature_c = 0.0
        self.heading_reference_deg = 0.0

        # UI motion estimates derived from live IMU samples (not motor commands).
        self._motion_speed_est = 0.0
        self._motion_speed_peak = 0.0
        self._motion_forward_accel = 0.0
        self._motion_last_activity = 0.0

        # Magnetometer runtime state.
        self.mag_available = False
        self.mag_adjust = {"x": 1.0, "y": 1.0, "z": 1.0}
        self.mag_heading_deg = 0.0
        self._yaw_initialized = False

    def _read_config(self) -> Dict[str, Any]:
        if not self.config_manager:
            return {}
        return self.config_manager.get("imu") or {}

    @staticmethod
    def _parse_sensor_type(value) -> str:
        text = str(value or "mpu6050").strip().lower().replace("-", "").replace("_", "")
        return "mpu9250" if "9250" in text else "mpu6050"

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

    @staticmethod
    def _quaternion_from_euler(roll_deg: float, pitch_deg: float, yaw_deg: float) -> Dict[str, float]:
        """Tait-Bryan ZYX (yaw-pitch-roll) angles -> orientation quaternion.

        Producing a single consistent quaternion (instead of letting the client
        recombine the three angles) avoids the axis coupling that appears when the
        mounting roll is near 180 degrees.
        """
        r = math.radians(roll_deg) * 0.5
        p = math.radians(pitch_deg) * 0.5
        y = math.radians(yaw_deg) * 0.5
        cr, sr = math.cos(r), math.sin(r)
        cp, sp = math.cos(p), math.sin(p)
        cy, sy = math.cos(y), math.sin(y)
        return {
            "w": cr * cp * cy + sr * sp * sy,
            "x": sr * cp * cy - cr * sp * sy,
            "y": cr * sp * cy + sr * cp * sy,
            "z": cr * cp * sy - sr * sp * cy,
        }

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
        self.mag_available = False
        self._yaw_initialized = False

    async def configure(self, config: Dict[str, Any]):
        was_enabled = self.enabled
        was_running = self._running
        old_bus_id = self.bus_id
        old_address = self.address
        old_sensor_type = self.sensor_type

        self.enabled = bool(config.get("enabled", self.enabled))
        self.sensor_type = self._parse_sensor_type(config.get("sensor_type", self.sensor_type))
        self.bus_id = int(config.get("bus", self.bus_id))
        self.address = self._parse_address(config.get("i2c_address", self.address))
        self.sample_rate_hz = self._clamp_float(config.get("sample_rate_hz", self.sample_rate_hz), 5, 100)
        self.calibration_samples = int(self._clamp_float(config.get("calibration_samples", self.calibration_samples), 10, 500))
        self.gyro_deadband_dps = self._clamp_float(config.get("gyro_deadband_dps", self.gyro_deadband_dps), 0, 5)
        self.mag_declination_deg = self._clamp_float(config.get("mag_declination_deg", self.mag_declination_deg), -180, 180)
        self.mag_yaw_invert = bool(config.get("mag_yaw_invert", self.mag_yaw_invert))

        if not was_running:
            if self.enabled:
                await self.start()
            return

        if not self.enabled:
            await self.stop()
            return

        if (
            not was_enabled
            or not self.available
            or old_bus_id != self.bus_id
            or old_address != self.address
            or old_sensor_type != self.sensor_type
        ):
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

        self.mag_available = False
        self._yaw_initialized = False
        if self.sensor_type == "mpu9250":
            try:
                self._initialize_magnetometer()
            except Exception as exc:
                self.mag_available = False
                logger.warning("AK8963 magnetometer init failed; falling back to gyro-only yaw: %s", exc)

        self._calibrate_gyro()
        self.available = True
        self.error = None
        self._last_sample_time = None
        logger.info(
            "IMU (%s) initialized on I2C bus %s address 0x%02x (magnetometer=%s)",
            self.sensor_type, self.bus_id, self.address, self.mag_available,
        )

    def _initialize_magnetometer(self):
        """Bring up the AK8963 magnetometer embedded in the MPU9250.

        The AK8963 sits on the MPU9250's auxiliary I2C bus. Enabling bypass mode
        exposes it on the main bus at 0x0C so we can talk to it directly.
        """
        # Enable I2C bypass so the AK8963 is reachable on the main bus.
        self._bus.write_byte_data(self.address, self.INT_PIN_CFG, 0x02)
        time.sleep(0.01)

        who = self._bus.read_byte_data(self.AK8963_ADDRESS, self.AK8963_WIA)
        if who != 0x48:
            raise RuntimeError(f"AK8963 not found (WHO_AM_I=0x{who:02x})")

        # Read factory sensitivity adjustment from the fuse ROM.
        self._bus.write_byte_data(self.AK8963_ADDRESS, self.AK8963_CNTL1, 0x00)  # power down
        time.sleep(0.01)
        self._bus.write_byte_data(self.AK8963_ADDRESS, self.AK8963_CNTL1, 0x0F)  # fuse ROM access
        time.sleep(0.01)
        asa = self._bus.read_i2c_block_data(self.AK8963_ADDRESS, self.AK8963_ASAX, 3)
        self.mag_adjust = {
            "x": (asa[0] - 128) / 256.0 + 1.0,
            "y": (asa[1] - 128) / 256.0 + 1.0,
            "z": (asa[2] - 128) / 256.0 + 1.0,
        }

        # Continuous measurement mode 2 (100 Hz), 16-bit output.
        self._bus.write_byte_data(self.AK8963_ADDRESS, self.AK8963_CNTL1, 0x00)
        time.sleep(0.01)
        self._bus.write_byte_data(self.AK8963_ADDRESS, self.AK8963_CNTL1, 0x16)
        time.sleep(0.01)

        self.mag_available = True
        logger.info("AK8963 magnetometer ready; sensitivity adjust=%s", self.mag_adjust)

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

        result = {
            "accel": {"x": word(0), "y": word(2), "z": word(4)},
            "temperature_raw": word(6),
            "gyro": {"x": word(8), "y": word(10), "z": word(12)},
            "mag": None,
        }

        if self.mag_available:
            result["mag"] = self._read_magnetometer()

        return result

    def _read_magnetometer(self) -> Optional[Dict[str, float]]:
        """Read one AK8963 sample in the accel/gyro body frame, or None if not ready.

        The AK8963 axes do not match the MPU9250 accel/gyro axes: its X maps to the
        body Y, its Y to the body X, and its Z is inverted. We remap here so the
        magnetometer shares the same frame as the rest of the IMU.
        """
        try:
            st1 = self._bus.read_byte_data(self.AK8963_ADDRESS, self.AK8963_ST1)
            if not (st1 & 0x01):  # DRDY not set yet
                return None

            # 6 data bytes (little-endian) followed by ST2, which must be read to
            # complete the measurement cycle.
            data = self._bus.read_i2c_block_data(self.AK8963_ADDRESS, self.AK8963_HXL, 7)
            st2 = data[6]
            if st2 & 0x08:  # HOFL: magnetic overflow, sample invalid
                return None

            def word_le(low: int, high: int) -> int:
                value = (data[high] << 8) | data[low]
                return value - 65536 if value & 0x8000 else value

            raw_x = word_le(0, 1) * self.MAG_SCALE_UT * self.mag_adjust["x"]
            raw_y = word_le(2, 3) * self.MAG_SCALE_UT * self.mag_adjust["y"]
            raw_z = word_le(4, 5) * self.MAG_SCALE_UT * self.mag_adjust["z"]

            # Remap AK8963 axes into the accel/gyro body frame.
            return {"x": raw_y, "y": raw_x, "z": -raw_z}
        except Exception as exc:
            logger.debug("Magnetometer read failed: %s", exc)
            return None

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

        mag = raw.get("mag")

        with self._lock:
            alpha = 0.96
            if dt <= 0:
                roll = roll_acc
                pitch = pitch_acc
            else:
                roll = alpha * (self.angles["roll"] + gyro["x"] * dt) + (1 - alpha) * roll_acc
                pitch = alpha * (self.angles["pitch"] + gyro["y"] * dt) + (1 - alpha) * pitch_acc

            # Integrate the gyro first; this is the responsive, low-latency yaw.
            yaw_gyro = self._normalize_angle(self.angles["yaw"] + gyro["z"] * dt)
            # Separate pure-gyro accumulator for closed-loop control (no mag pull).
            self.gyro_yaw_deg = self._normalize_angle(self.gyro_yaw_deg + gyro["z"] * dt)

            mag_heading = self._compute_mag_heading(mag, roll, pitch) if mag else None
            if mag_heading is not None:
                self.mag = mag
                self.mag_heading_deg = mag_heading
                if not self._yaw_initialized:
                    # Snap to the absolute heading on the first valid sample so we
                    # don't slowly ramp in from zero.
                    yaw = mag_heading
                    self._yaw_initialized = True
                else:
                    # Complementary fusion: trust the gyro short-term, nudge toward
                    # the drift-free magnetic heading over time.
                    mag_alpha = 0.98
                    error = self._normalize_angle(mag_heading - yaw_gyro)
                    yaw = self._normalize_angle(yaw_gyro + (1.0 - mag_alpha) * error)
            else:
                yaw = yaw_gyro

            self.accel = accel
            self.gyro = gyro
            pitch_rad = math.radians(pitch)
            roll_rad = math.radians(roll)
            # Gravity in body frame (g) so we can isolate dynamic acceleration.
            gravity_x = -math.sin(pitch_rad)
            gravity_y = math.sin(roll_rad) * math.cos(pitch_rad)
            forward_dynamic = accel["x"] - gravity_x
            self._motion_forward_accel = forward_dynamic
            if dt > 0:
                self._motion_speed_est += forward_dynamic * dt * 3.0
            self._motion_speed_est = max(0.0, min(1.0, self._motion_speed_est * 0.997))
            self._motion_speed_peak = max(
                self._motion_speed_est,
                self._motion_speed_peak * 0.998,
            )
            if abs(forward_dynamic) > 0.03 or abs(gyro["z"]) > 2.0:
                self._motion_last_activity = time.time()
            if self.sensor_type == "mpu9250":
                # MPU9250: TEMP_degC = (raw - roomOffset)/333.87 + 21
                self.temperature_c = raw["temperature_raw"] / 333.87 + 21.0
            else:
                self.temperature_c = raw["temperature_raw"] / 340.0 + 36.53
            self.angles = {"roll": roll, "pitch": pitch, "yaw": yaw}
            # Build the display orientation from the instantaneous accelerometer
            # tilt (not the gyro-fused roll/pitch) so the 3D model tracks the real
            # pose immediately without the integration overshoot. Pitch is negated
            # so a real nose-up tilt shows as nose-up in the visualizer.
            self.orientation_quat = self._quaternion_from_euler(roll_acc, -pitch_acc, yaw)
            self.last_update = time.time()

    def _compute_mag_heading(self, mag: Dict[str, float], roll_deg: float, pitch_deg: float) -> Optional[float]:
        """Tilt-compensated magnetic heading in degrees, in the gyro-yaw convention.

        Uses the fused roll/pitch to project the magnetometer onto the horizontal
        plane (ST AN3192 form). Sign and declination are configurable because they
        depend on mounting and location; flip ``mag_yaw_invert`` if the fused yaw
        oscillates instead of settling.
        """
        try:
            roll = math.radians(roll_deg)
            pitch = math.radians(pitch_deg)
            mx, my, mz = mag["x"], mag["y"], mag["z"]

            xh = mx * math.cos(pitch) + mz * math.sin(pitch)
            yh = (
                mx * math.sin(roll) * math.sin(pitch)
                + my * math.cos(roll)
                - mz * math.sin(roll) * math.cos(pitch)
            )

            heading = math.degrees(math.atan2(yh, xh))
            if self.mag_yaw_invert:
                heading = -heading
            return self._normalize_angle(heading + self.mag_declination_deg)
        except Exception as exc:
            logger.debug("Mag heading computation failed: %s", exc)
            return None

    def is_ready(self) -> bool:
        return bool(self.enabled and self.available and self.calibrated)

    def reset_heading_reference(self):
        # Reference the pure-gyro yaw: closed-loop control must not be dragged by
        # the magnetometer (motor interference) during a manoeuvre.
        with self._lock:
            self.heading_reference_deg = self.gyro_yaw_deg
        logger.info("IMU heading reference reset to %.2f degrees (gyro)", self.heading_reference_deg)

    def set_heading_reference(self, heading_deg: float):
        """Pin the straight-line hold reference to a specific (gyro-frame) heading.

        Used after a turn so the robot holds the *intended* heading (start + target)
        even if the turn stopped a few degrees short or long; the straight-line
        controller then trims the residual error away.
        """
        with self._lock:
            self.heading_reference_deg = self._normalize_angle(heading_deg)
        logger.info("IMU heading reference set to %.2f degrees", self.heading_reference_deg)

    def get_heading_error_deg(self) -> float:
        with self._lock:
            return self._normalize_angle(self.gyro_yaw_deg - self.heading_reference_deg)

    def angle_delta_from(self, start_yaw: float) -> float:
        # Delta on the pure-gyro yaw, for EMI-immune turn measurement.
        with self._lock:
            return self._normalize_angle(self.gyro_yaw_deg - start_yaw)

    def get_yaw_deg(self) -> float:
        # Returns the control yaw (pure gyro) so a captured start matches
        # angle_delta_from(). Use get_data()["heading"] for the absolute heading.
        with self._lock:
            return float(self.gyro_yaw_deg)

    def get_gyro_rate_z(self) -> float:
        """Current yaw angular rate in deg/s (used to brake turns before overshoot)."""
        with self._lock:
            return float(self.gyro.get("z", 0.0))

    def get_motion_display(self, circuit_active: bool = False) -> Optional[Dict[str, float]]:
        """Normalized speed/turn/acceleration for the web UI from IMU measurements."""
        if not self.available:
            return None
        with self._lock:
            turn = max(-1.0, min(1.0, self.gyro["z"] / 120.0))
            acceleration = max(-1.0, min(1.0, self._motion_forward_accel / 0.25))
            speed = self._motion_speed_est
            # IMU cannot read steady cruise speed (≈0 dynamic accel). Hold a slow
            # decay from recent motion so the bar does not snap to zero mid-run.
            if circuit_active and time.time() - self._motion_last_activity < 4.0:
                speed = max(speed, self._motion_speed_peak * 0.85)
            speed = max(0.0, min(1.0, speed))
            return {
                "speed": speed,
                "turn": turn,
                "acceleration": acceleration,
                "gyroRateZ": self.gyro["z"],
                "gyroYaw": self.gyro_yaw_deg,
                "forwardAccelG": self._motion_forward_accel,
            }

    def get_data(self) -> Dict[str, Any]:
        with self._lock:
            heading_error = self._normalize_angle(self.gyro_yaw_deg - self.heading_reference_deg)
            return {
                "enabled": self.enabled,
                "available": self.available,
                "calibrated": self.calibrated,
                "sensorType": self.sensor_type,
                "magnetometer": self.mag_available,
                "bus": self.bus_id,
                "address": f"0x{self.address:02x}",
                "accel": dict(self.accel),
                "gyro": dict(self.gyro),
                "mag": dict(self.mag),
                "angles": dict(self.angles),
                "quaternion": dict(self.orientation_quat),
                "heading": self.angles["yaw"],
                "magHeading": self.mag_heading_deg,
                "headingReference": self.heading_reference_deg,
                "headingError": heading_error,
                "gyroYaw": self.gyro_yaw_deg,
                "forwardAccelG": self._motion_forward_accel,
                "temperature": self.temperature_c,
                "lastUpdated": int(self.last_update * 1000) if self.last_update else None,
                "error": self.error,
            }
