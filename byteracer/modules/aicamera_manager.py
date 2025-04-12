import time
import logging
import threading
import math

logger = logging.getLogger(__name__)

class AICameraCameraManager:
    """
    Manages higher-level AI camera capabilities, specifically:
      1) Traffic light color detection and speed control (red, green, orange).
      2) Face detection + following (forward/back & turn).
      3) Pose detection.
      4) Traffic-sign detection.
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

        # Pose detection
        self.pose_detection_thread = None
        self.pose_detection_active = False

        # Traffic-sign detection
        self.traffic_sign_detection_thread = None
        self.traffic_sign_detection_active = False

        # ---------------------------------------------------------
        # Face following parameters (adjust for your system)
        # ---------------------------------------------------------
        self.TARGET_FACE_AREA = 10.0    # (in %) Ideal face size in the frame
        self.FORWARD_FACTOR   = 1500.0  # Speed scaling factor
        self.MAX_SPEED        = 75      # maximum absolute speed (±75)
        self.SPEED_DEAD_ZONE  = 50      # movement dead zone around 0 speed

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
            # detection example:
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
                x_offset_ratio = (face_x / camera_width) - 0.5
                target_x_angle = x_offset_ratio * 180  # scale up to ±90

                dx = target_x_angle - self.x_angle
                self.x_angle += 0.2 * dx
                self.x_angle = self.clamp_number(self.x_angle, self.PAN_MIN_ANGLE, self.PAN_MAX_ANGLE)
                self.px.set_cam_pan_angle(int(self.x_angle))

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
                        break  # highest priority => immediately stop
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
    # Traffic-Sign Detection
    # ------------------------------------------------------------------    
    def start_traffic_sign_detection(self):
        """
        Spawns a background thread to do traffic sign detection.
        """
        if hasattr(self, 'traffic_sign_detection_active') and self.traffic_sign_detection_active:
            logger.warning("Traffic sign detection is already running!")
            return

        logger.info("Starting traffic sign detection ...")
        self.traffic_sign_detection_active = True
        
        # Reset camera angles
        self.x_angle = 0
        self.y_angle = 0

        # Enable traffic sign detection in camera_manager
        self.camera_manager.switch_trafic_sign_detect(True)

        # Start thread
        self.traffic_sign_detection_thread = threading.Thread(
            target=self._traffic_sign_detection_loop,
            daemon=True
        )
        self.traffic_sign_detection_thread.start()

    def stop_traffic_sign_detection(self):
        """
        Signals the traffic-sign-detection loop to stop and waits for thread to end.
        """
        if not hasattr(self, 'traffic_sign_detection_active') or not self.traffic_sign_detection_active:
            logger.warning("Traffic sign detection not currently running!")
            return

        logger.info("Stopping traffic sign detection ...")
        self.traffic_sign_detection_active = False

        if self.traffic_sign_detection_thread and self.traffic_sign_detection_thread.is_alive():
            self.traffic_sign_detection_thread.join(timeout=2.0)

        self.traffic_sign_detection_thread = None

        # Optionally disable traffic sign detection
        self.camera_manager.switch_trafic_sign_detect(False)    
    def _traffic_sign_detection_loop(self):
        """
        Continuously checks for traffic sign data from camera_manager.
        Locks camera onto detected signs by adjusting pan/tilt servos.
        Adjust as needed to act on 'stop', 'left', 'right', etc.
        """
        logger.info("Traffic sign detection loop started.")
        
        # Suppose your camera resolution is 640 x 480 (match with face following)
        camera_width = 640
        camera_height = 480

        while self.traffic_sign_detection_active:
            # Expecting something like:
            # {
            #    'traffic_sign_n': ...,
            #    'x': ...,
            #    'y': ...,
            #    'w': ...,
            #    'h': ...,
            #    't': 'stop'/'left'/'right'/'forward'/'none', 
            #    'acc': ...
            # }
            detection = self.camera_manager.detect_obj_parameter('traffic_sign')
            # Implement how your camera_manager returns these fields

            if detection.get('traffic_sign_detected', False):
                sign_type = detection.get('traffic_sign_type', 'none')
                x = detection.get('x', 0)
                y = detection.get('y', 0)
                acc = detection.get('acc', 0)
                w = detection.get('w', 0)
                h = detection.get('h', 0)
                
                # ---------------------------------------------
                # Camera lock-on to center sign in frame
                # ---------------------------------------------
                x_offset_ratio = (x / camera_width) - 0.5
                target_x_angle = x_offset_ratio * 180  # scale up to ±90

                dx = target_x_angle - self.x_angle
                self.x_angle += 0.2 * dx  # Smooth movement factor
                self.x_angle = self.clamp_number(self.x_angle, self.PAN_MIN_ANGLE, self.PAN_MAX_ANGLE)
                self.px.set_cam_pan_angle(int(self.x_angle))

                y_offset_ratio = 0.5 - (y / camera_height)
                target_y_angle = y_offset_ratio * 130  # Scale to tilt range

                dy = target_y_angle - self.y_angle
                self.y_angle += 0.2 * dy  # Smooth movement factor
                self.y_angle = self.clamp_number(self.y_angle, self.TILT_MIN_ANGLE, self.TILT_MAX_ANGLE)
                self.px.set_cam_tilt_angle(int(self.y_angle))
                
                logger.debug(f"Traffic Sign => type={sign_type}, confidence={acc}, center=({x},{y}), size=({w},{h}), " + 
                             f"camera pan={self.x_angle:.1f}, tilt={self.y_angle:.1f}")
                
                # If you want to do something special on "stop", "left", etc.
                # e.g. if sign_type == 'stop': self.px.forward(0)
            
            time.sleep(0.05)

        logger.info("Traffic sign detection loop stopped.")
