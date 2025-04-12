import time
import logging
import threading
import math

logger = logging.getLogger(__name__)

class AICameraCameraManager:
    """
    Manages higher-level AI camera capabilities, specifically:
      1) Traffic light color detection and speed control (red, green, orange).
      2) Face detection + following (including forward/back & turn).
    """

    def __init__(self, px, sensor_manager, camera_manager):
        # Robot control/hardware
        self.px = px
        self.sensor_manager = sensor_manager
        self.camera_manager = camera_manager

        logger.info("AI CAMERA INITIALIZED")

        # Face following angle states
        self.x_angle = 0
        self.y_angle = 0
        self.dir_angle = 0

        # Thread management
        self.face_follow_thread = None
        self.face_follow_active = False

        self.color_control_thread = None
        self.color_control_active = False

        # ---------------------------------------------------------
        # Face following parameters (adjust for your system)
        # ---------------------------------------------------------
        self.TARGET_FACE_AREA = 10.0    # (in %) Ideal face size in the frame
        self.FORWARD_FACTOR   = 1500.0  # Speed scaling factor
        self.MAX_SPEED        = 75      # maximum absolute speed (±75)
        self.SPEED_DEAD_ZONE  = 50       # movement dead zone around 0 speed

        # Steering constants
        self.TURN_FACTOR = 35.0         # final multiplier for turning

        # Camera servo ranges:
        self.PAN_MIN_ANGLE  = -90
        self.PAN_MAX_ANGLE  =  90
        self.TILT_MIN_ANGLE = -35
        self.TILT_MAX_ANGLE =  65

        # Steering servo limit => ±35° (change if physically only ±30°)
        self.STEER_MIN_ANGLE = -35
        self.STEER_MAX_ANGLE =  35

    def clamp_number(self, num, lower_bound, upper_bound):
        """Clamp 'num' between 'lower_bound' and 'upper_bound'."""
        return max(min(num, max(lower_bound, upper_bound)),
                   min(lower_bound, upper_bound))

    # ------------------------------------------------------------------
    # Face Following
    # ------------------------------------------------------------------
    def start_face_following(self):
        if self.face_follow_active:
            logger.warning("Face following is already running!")
            return

        logger.info("Starting face following ...")
        self.face_follow_active = True
        # Enable face detection in camera_manager
        self.camera_manager.switch_face_detect(True)

        # Reset angles
        self.x_angle = 0
        self.y_angle = 0
        self.dir_angle = 0

        # Start thread
        self.face_follow_thread = threading.Thread(
            target=self._face_follow_loop,
            daemon=True
        )
        self.face_follow_thread.start()

    def stop_face_following(self):
        if not self.face_follow_active:
            logger.warning("Face following is not currently running!")
            return

        logger.info("Stopping face following ...")
        self.face_follow_active = False

        if self.face_follow_thread and self.face_follow_thread.is_alive():
            self.face_follow_thread.join(timeout=2.0)

        self.face_follow_thread = None
        self.camera_manager.switch_face_detect(False)
        # Stop robot
        self.px.forward(0)

    def _face_follow_loop(self):
        """
        Loop that continuously retrieves face detection data from camera_manager
        and steers the robot to follow the face while allowing both forward & reverse.
        We also have a speed dead zone to prevent micro-movements when near the target area.
        """

        logger.info("Face-follow loop started.")

        def sign(x):
            return 1 if x > 0 else (-1 if x < 0 else 0)

        def turn_function(x_offset):
            """
            Polynomial approach for strong turning if face is off-center.
            'factor' saturates the steering angle more quickly if large.
            """
            factor = 10.0
            return factor * sign(x_offset) * abs(x_offset**2)

        # Suppose your camera resolution is 640 x 480 (change if needed)
        camera_width = 640
        camera_height = 480

        while self.face_follow_active:
            detection = self.camera_manager.detect_obj_parameter('human')
            # detection e.g.:
            # {
            #   'human_detected': bool,
            #   'human_x': int,
            #   'human_y': int,
            #   'human_n': int,
            #   'human_w': int,
            #   'human_h': int
            # }

            if detection.get('human_detected', False):
                face_x = detection['human_x']
                face_y = detection['human_y']
                face_w = detection.get('human_w', 0)
                face_h = detection.get('human_h', 0)

                # ---------------------------------------------
                # 1) Pan/Tilt the camera
                # ---------------------------------------------
                # Horizontal offset => range [-0.5..+0.5]
                x_offset_ratio = (face_x / camera_width) - 0.5
                target_x_angle = x_offset_ratio * 180  # scale up to ±90

                dx = target_x_angle - self.x_angle
                self.x_angle += 0.2 * dx
                self.x_angle = self.clamp_number(self.x_angle, self.PAN_MIN_ANGLE, self.PAN_MAX_ANGLE)
                self.px.set_cam_pan_angle(int(self.x_angle))

                # Vertical offset => range [ +0.5.. -0.5 ]
                y_offset_ratio = 0.5 - (face_y / camera_height)
                target_y_angle = y_offset_ratio * 130

                dy = target_y_angle - self.y_angle
                self.y_angle += 0.2 * dy
                self.y_angle = self.clamp_number(self.y_angle, self.TILT_MIN_ANGLE, self.TILT_MAX_ANGLE)
                self.px.set_cam_tilt_angle(int(self.y_angle))

                # ---------------------------------------------
                # 2) Forward/backward speed with dead zone
                # ---------------------------------------------
                face_area_percent = (face_w * face_h) / (camera_width * camera_height) * 100.0
                # If face_area_percent > TARGET_FACE_AREA => raw_speed < 0 => go backward
                raw_speed = (self.TARGET_FACE_AREA - face_area_percent) * (self.FORWARD_FACTOR / 100.0)

                # clamp to ±MAX_SPEED
                if raw_speed > self.MAX_SPEED:
                    raw_speed = self.MAX_SPEED
                elif raw_speed < -self.MAX_SPEED:
                    raw_speed = -self.MAX_SPEED

                # dead zone => no movement if small absolute speed
                if abs(raw_speed) < self.SPEED_DEAD_ZONE:
                    raw_speed = 0

                # ---------------------------------------------
                # 3) Steering => invert if going backward
                # ---------------------------------------------
                steer_val = turn_function(x_offset_ratio) * self.TURN_FACTOR
                # clamp to ±(some servo limit)
                steer_val = self.clamp_number(steer_val, self.STEER_MIN_ANGLE, self.STEER_MAX_ANGLE)

                if raw_speed > 0:
                    # FORWARD
                    self.px.set_dir_servo_angle(steer_val)
                    self.px.forward(int(raw_speed))
                elif raw_speed < 0:
                    # BACKWARD => invert steering
                    self.px.set_dir_servo_angle(-steer_val)
                    self.px.backward(int(abs(raw_speed)))
                else:
                    # raw_speed == 0 => stop
                    self.px.forward(0)

                logger.debug(
                    f"[FACE] area={face_area_percent:.1f}%, offsetX={x_offset_ratio:.2f} => "
                    f"speed={raw_speed:.1f}, steer={steer_val:.1f}, "
                    f"pan={self.x_angle:.1f}, tilt={self.y_angle:.1f}"
                )
            else:
                # No face => stop
                self.px.forward(0)
                logger.debug("No face detected => STOP.")

            time.sleep(0.05)

        logger.info("Face-follow loop stopped.")

    # ------------------------------------------------------------------
    # Traffic-Light Color Detection
    # ------------------------------------------------------------------
    def start_color_control(self):
        """
        Spawns a background thread to do traffic-light color detection 
        and speed control (red => stop, orange => 50, green => 100).
        """
        if self.color_control_active:
            logger.warning("Traffic-light color detect is already running!")
            return

        logger.info("Starting color control (red/green/orange) ...")
        self.color_control_active = True

        # Enable detection of red, green, orange in camera_manager
        self.camera_manager.color_detect(["red", "green", "orange"])

        # Start thread
        self.color_control_thread = threading.Thread(
            target=self._color_control_loop,
            daemon=True
        )
        self.color_control_thread.start()

    def stop_color_control(self):
        """
        Signals the color-control loop to stop and waits for thread to end.
        """
        if not self.color_control_active:
            logger.warning("Traffic-light color detect not currently running!")
            return

        logger.info("Stopping color control loop ...")
        self.color_control_active = False

        if self.color_control_thread and self.color_control_thread.is_alive():
            self.color_control_thread.join(timeout=2.0)

        self.color_control_thread = None

        # Optionally disable color detection
        self.camera_manager.switch_color_detect(False)
        # Stop the robot
        self.px.forward(0)

    def _color_control_loop(self):
        """
        Loop that continuously retrieves color detection data from camera_manager
        and adjusts speed based on whether red/green/orange is found.
        """
        logger.info("Color control loop started (red/green/orange).")

        while self.color_control_active:
            # detection e.g. {
            #   'colors_detected': [ { 'color_name':'red','color_n':2,...}, ... ],
            #   'any_color_found': True/False
            # }
            detection = self.camera_manager.detect_obj_parameter('color')

            desired_speed = 0  # default => stop
            if detection.get('any_color_found', False):
                for color_info in detection['colors_detected']:
                    cname = color_info['color_name']
                    if cname == 'red':
                        desired_speed = 0
                        break  # highest priority
                    elif cname == 'green':
                        desired_speed = max(desired_speed, 100)
                    elif cname == 'orange':
                        if desired_speed < 100:
                            desired_speed = 50
                    # ignoring other colors
            else:
                # no color => stop
                desired_speed = 0

            self.px.forward(desired_speed)
            logger.debug(f"Traffic Light => Speed = {desired_speed}")

            time.sleep(0.05)

        logger.info("Color control loop stopped.")


    # ------------------------------------------------------------------
    # Pose Detection
    # ------------------------------------------------------------------

    def start_pose_detection(self):
        """
        Spawns a background thread to do pose detection.
        """
        if self.pose_detection_active:
            logger.warning("Pose detection is already running!")
            return

        logger.info("Starting pose detection ...")
        self.pose_detection_active = True

        # Enable pose detection in camera_manager
        self.camera_manager.switch_pose_detect(True)

        # Start thread
        self.pose_detection_thread = threading.Thread(
            target=self._pose_detection_loop,
            daemon=True
        )
        self.pose_detection_thread.start()
    
    def stop_pose_detection(self):
        """
        Signals the pose-detection loop to stop and waits for thread to end.
        """
        if not self.pose_detection_active:
            logger.warning("Pose detection not currently running!")
            return

        logger.info("Stopping pose detection ...")
        self.pose_detection_active = False

        if self.pose_detection_thread and self.pose_detection_thread.is_alive():
            self.pose_detection_thread.join(timeout=2.0)

        self.pose_detection_thread = None

        # Optionally disable pose detection
        self.camera_manager.switch_pose_detect(False)

    
    # ------------------------------------------------------------------
    # Traffic-Sign Detection
    # ------------------------------------------------------------------

    def start_traffic_sign_detection(self):
        