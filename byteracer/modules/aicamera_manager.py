import time
import logging
import threading
from enum import Enum, auto

logger = logging.getLogger(__name__)

class AICameraCameraManager:
    """
    Manages higher-level AI camera capabilities, specifically:
      1) "Traffic light" color detection and speed control (red, green, orange).
      2) Face detection + following.

    We provide start/stop methods for each feature. 
    Internally, each runs an infinite loop in a separate thread 
    until stopped by the user.
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
        
        # Face following parameters
        self.face_min_distance = 10  # Stop if face area is larger than this paercentage of screen
        self.face_max_distance = 3  # Speed up if face area is smaller than this percentage
        self.face_optimal_distance = 5  # Ideal face size percentage of screen area

    def clamp_number(self, num, lower_bound, upper_bound):
        """Clamp 'num' between 'lower_bound' and 'upper_bound'."""
        return max(min(num, max(lower_bound, upper_bound)), 
                   min(lower_bound, upper_bound))

    # ------------------------------------------------------------------
    # Face Following
    # ------------------------------------------------------------------
    def start_face_following(self):
        """
        Spawns a background thread to continuously detect & follow a face,
        until stop_face_following() is called.
        """
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
        """
        Signals the face-follow loop to stop and waits for thread to end.
        """
        if not self.face_follow_active:
            logger.warning("Face following is not currently running!")
            return

        logger.info("Stopping face following ...")
        self.face_follow_active = False

        # Optionally wait for the thread to exit
        if self.face_follow_thread and self.face_follow_thread.is_alive():
            self.face_follow_thread.join(timeout=2.0)

        self.face_follow_thread = None
        # Optionally disable face detection
        self.camera_manager.switch_face_detect(False)
        # Stop the robot
        self.px.forward(0)    
    
    def _face_follow_loop(self):
        """
        Loop that continuously retrieves face detection data from camera_manager
        and steers the robot to follow the face while maintaining optimal distance.
        """
        logger.info("Face-follow loop started.")
        default_speed = 50  # Base speed
        max_speed = 75      # Maximum speed when face is far away
        min_speed = 20      # Minimum speed when approaching optimal distance

        while self.face_follow_active:
            detection = self.camera_manager.detect_obj_parameter('human')
            # detection: {
            #   'human_detected': bool,
            #   'human_x': int,
            #   'human_y': int,
            #   'human_n': int,
            #   'human_w': int,
            #   'human_h': int,
            # }

            if detection.get('human_detected', False):
                face_x = detection['human_x']
                face_y = detection['human_y']
                face_w = detection.get('human_w', 0)
                face_h = detection.get('human_h', 0)

                # Typically 640x480, or your camera's actual size
                camera_width = 640
                camera_height = 480
                
                # Calculate face area as percentage of screen area
                face_area = (face_w * face_h) / (camera_width * camera_height) * 100
                
                # Dynamic speed calculation based on face size (distance)
                speed = 0  # Default to stopped
                
                # Calculate the center offset of the face
                center_x_offset = abs((face_x / camera_width) - 0.5)  # 0 = center, 0.5 = edge
                
                if face_area >= self.face_min_distance:
                    # Face is too close - stop
                    speed = 0
                    logger.debug(f"Face too close (area: {face_area:.1f}%) => STOP")
                elif face_area <= self.face_max_distance:
                    # Face is far away - move faster
                    speed = max_speed
                    logger.debug(f"Face far away (area: {face_area:.1f}%) => FAST")
                else:
                    # Face is at medium distance - adjust speed proportionally
                    # Map face area from [face_max_distance, face_min_distance] to [max_speed, min_speed]
                    ratio = (face_area - self.face_max_distance) / (self.face_min_distance - self.face_max_distance)
                    speed = max_speed - ratio * (max_speed - min_speed)
                    logger.debug(f"Face at medium distance (area: {face_area:.1f}%) => speed {speed:.1f}")
                
                # Reduce speed further if face is not centered (for smoother turning)
                center_factor = 1.0 - min(center_x_offset * 1.5, 0.5)  # Reduce speed by up to 50% when turning
                speed = speed * center_factor                # Pan camera angle - balanced approach with damping
                # More responsive near edges but with damping to prevent oscillation
                center_x_offset = abs((face_x / camera_width) - 0.5)  # 0 = center, 0.5 = edge
                edge_factor = 1.0 + (center_x_offset * 1.5)  # More modest boost near edges (up to 1.75x)
                
                # Match hardware limits mentioned in documentation (-90 to 90)
                target_x_angle = ((face_x / camera_width) - 0.5) * 70  # Reasonable angle range
                
                # Calculate optimal adjustment rate based on distance from target
                # Larger adjustments when far from target, smaller when close
                angle_distance = abs(target_x_angle - self.x_angle)
                adjustment_scale = min(1.0, angle_distance / 10.0)  # Scale from 0.0-1.0 based on distance
                
                # Apply moderate base adjustment rate with custom scaling
                self.x_angle += (target_x_angle - self.x_angle) * 0.25 * edge_factor * adjustment_scale
                self.x_angle = self.clamp_number(self.x_angle, -35, 35)  # Hardware-appropriate angle limits
                self.px.set_cam_pan_angle(int(self.x_angle))

                # Tilt camera angle - balanced approach with damping
                center_y_offset = abs((face_y / camera_height) - 0.5)
                edge_y_factor = 1.0 + (center_y_offset * 1.5)  # More modest boost
                
                # Match hardware limits mentioned in documentation (-35 to 65)
                # Using asymmetric range for tilt as per hardware spec
                target_y_angle = ((0.5 - (face_y / camera_height)) * 50)  # Moderate angle range
                
                # Calculate optimal adjustment rate for tilt
                angle_y_distance = abs(target_y_angle - self.y_angle)
                adjustment_y_scale = min(1.0, angle_y_distance / 10.0)
                
                # Apply moderate adjustment with damping
                self.y_angle += (target_y_angle - self.y_angle) * 0.25 * edge_y_factor * adjustment_y_scale
                self.y_angle = self.clamp_number(self.y_angle, -35, 35)  # Match hardware limitations
                self.px.set_cam_tilt_angle(int(self.y_angle))

                # Steering angle - more responsive but still smooth
                # Make steering more proportional to face position
                target_dir_angle = self.x_angle * 0.8  # Steering follows camera but not as extreme
                
                # Apply smoother steering for more natural movement
                if abs(self.dir_angle - target_dir_angle) > 5:
                    # Faster adjustment when far from target
                    self.dir_angle += (target_dir_angle - self.dir_angle) * 0.3
                else:
                    # Slower, smoother adjustment when close to target
                    self.dir_angle += (target_dir_angle - self.dir_angle) * 0.1
                
                self.dir_angle = self.clamp_number(self.dir_angle, -35, 35)
                self.px.set_dir_servo_angle(self.dir_angle)

                # Apply calculated speed
                self.px.forward(int(speed))
                logger.debug(f"Face found => steer={self.dir_angle:.1f}, speed={speed:.1f}, area={face_area:.1f}%")
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
                        # only override if we haven't seen green yet
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
