import time
import logging
import threading
import math
import os
import sys
import numpy as np
import cv2
from ultralytics import YOLO
import asyncio
logger = logging.getLogger(__name__)

class AICameraCameraManager:
    """
    Manages higher-level AI camera capabilities, specifically:
      1) Traffic light color detection and speed control (red, yellow, green).
      2) Face detection + following (forward/back & turn).
      3) Pose detection.
      4) Traffic-sign detection (stop signs, turn right signs).
      5) YOLO object detection using camera feed.
      
    Supported traffic signs and behaviors:
    - Red light: Robot stops and waits for green
    - Yellow light: Robot stops and waits for green
    - Green light: Robot proceeds at low speed
    - Stop sign: Robot stops for 2 seconds then proceeds
    - Right turn sign: Robot turns right after a 2-second delay
    """
    def __init__(self, px, sensor_manager, camera_manager, tts_manager, config_manager, led_manager):
        # Robot control/hardware
        self.px = px
        self.sensor_manager = sensor_manager
        self.camera_manager = camera_manager
        self.tts_manager = tts_manager
        self.config_manager = config_manager
        self.led_manager = led_manager

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
        
        # LED blinking state
        self.led_blink_pattern = None
        
        # YOLO object detection
        self.yolo_model = None
        self.yolo_detection_thread = None
        self.yolo_detection_active = False
        self.yolo_min_confidence = 0.5
        self.yolo_results = []
        self.yolo_object_count = 0
        # Extract camera width and height from config
        camera_size = self.config_manager.get("camera.camera_size")
        self.camera_width = camera_size[0]  # First element is width
        self.camera_height = camera_size[1]  # Second element is height

        # Traffic light state variables
        self.traffic_light_state = None  # Can be "red", "green", "yellow" or None
        self.traffic_light_detected = False
        self.waiting_for_green = False  # Flag to track if we're waiting for green after seeing red
        self.distance_threshold_cm = 30  # Object must be closer than this distance (in cm) for action
        self.ignore_traffic_lights_until = 0  # Timestamp to ignore traffic lights until
        
        # Stop sign state variables
        self.stop_sign_detected = False
        self.stop_sign_timer = None  # For tracking the 2-second stop duration
        self.waiting_at_stop_sign = False
        self.ignore_stop_signs_until = 0  # Timestamp to ignore stop signs until
        
        # Right turn sign state variables 
        self.right_turn_sign_detected = False
        self.right_turn_timer = None  # For tracking the delay before turning
        self.executing_right_turn = False
        self.right_turn_time = 2.0  # Duration of a right turn in seconds, can be adjusted for calibration
        self.right_turn_pending = False  # New flag to track if a right turn is pending
        
        # Continuous turning state
        self.continuous_turning = False  # Flag to track if continuous turning is active
        
        # Auto-load YOLO model if available in modules directory
        self.model_path = os.path.join(os.path.dirname(__file__), 'model_ncnn_model')
        if os.path.exists(self.model_path):
            try:
                # Try to load the model during initialization but don't block if it fails
                threading.Thread(target=self.load_yolo_model, args=(self.model_path,), daemon=True).start()
                logger.info(f"Started auto-loading YOLO model from {self.model_path}")
            except Exception as e:
                logger.warning(f"Auto-loading YOLO model failed: {e}")
        else:
            logger.warning(f"YOLO model not found at {self.model_path}")
        
        # Bounding box colors (Tableau 10 color scheme)
        self.bbox_colors = [(164,120,87), (68,148,228), (93,97,209), (178,182,133), (88,159,106), 
                           (96,202,231), (159,124,168), (169,162,241), (98,118,150), (172,176,184)]

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
        
        # Start LED tracking pattern
        self.start_tracking_pulse()

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
        
        # Stop LED tracking pattern
        self.stop_all_led_patterns()
        
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
        camera_width = self.camera_width
        camera_height = self.camera_height

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
        # if self.color_control_active:
        #     logger.warning("Traffic-light color detect is already running!")
        #     return

        # logger.info("Starting color control (red/green/orange) ...")
        # self.color_control_active = True
        # # Enable detection of red, green, orange in camera_manager
        # self.camera_manager.color_detect(["red", "green", "orange"])

        # # Start thread
        # self.color_control_thread = threading.Thread(
        #     target=self._color_control_loop,
        #     daemon=True
        # )
        # self.color_control_thread.start()
        return

    def stop_color_control(self):
        """
        Signals the color-control loop to stop and waits for thread to end.
        """
        # if not self.color_control_active:
        #     logger.warning("Traffic-light color detect not currently running!")
        #     return

        # logger.info("Stopping color control loop ...")
        # self.color_control_active = False

        # if self.color_control_thread and self.color_control_thread.is_alive():
        #     self.color_control_thread.join(timeout=2.0)

        # self.color_control_thread = None

        # # Optionally disable color detection
        # self.camera_manager.switch_color_detect(False)
        # # Stop the robot
        # self.px.forward(0)
        return

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
    # def start_traffic_sign_detection(self):
    #     """
    #     Spawns a background thread to do traffic sign detection.
    #     """
    #     if hasattr(self, 'traffic_sign_detection_active') and self.traffic_sign_detection_active:
    #         logger.warning("Traffic sign detection is already running!")
    #         return

    #     logger.info("Starting traffic sign detection ...")
    #     self.traffic_sign_detection_active = True
        
    #     # Reset camera angles
    #     self.x_angle = 0
    #     self.y_angle = 0

    #     # Enable traffic sign detection in camera_manager
    #     self.camera_manager.switch_trafic_sign_detect(True)

    #     # Start thread
    #     self.traffic_sign_detection_thread = threading.Thread(
    #         target=self._traffic_sign_detection_loop,
    #         daemon=True
    #     )
    #     self.traffic_sign_detection_thread.start()

    # def stop_traffic_sign_detection(self):
    #     """
    #     Signals the traffic-sign-detection loop to stop and waits for thread to end.
    #     """
    #     if not hasattr(self, 'traffic_sign_detection_active') or not self.traffic_sign_detection_active:
    #         logger.warning("Traffic sign detection not currently running!")
    #         return

    #     logger.info("Stopping traffic sign detection ...")
    #     self.traffic_sign_detection_active = False

    #     if self.traffic_sign_detection_thread and self.traffic_sign_detection_thread.is_alive():
    #         self.traffic_sign_detection_thread.join(timeout=2.0)

    #     self.traffic_sign_detection_thread = None

    #     # Optionally disable traffic sign detection
    #     self.camera_manager.switch_trafic_sign_detect(False)    
    # def _traffic_sign_detection_loop(self):
    #     """
    #     Continuously checks for traffic sign data from camera_manager.
    #     Locks camera onto detected signs by adjusting pan/tilt servos.
    #     Adjust as needed to act on 'stop', 'left', 'right', 'forward'/'none', 
    #     """
    #     logger.info("Traffic sign detection loop started.")
        
    #     # Suppose your camera resolution is 640 x 480 (match with face following)
    #     camera_width = 640
    #     camera_height = 480

    #     while self.traffic_sign_detection_active:
    #         # Expecting something like:
    #         # {
    #         #    'traffic_sign_n': ...,
    #         #    'x': ...,
    #         #    'y': ...,
    #         #    'w': ...,
    #         #    'h': ...,
    #         #    't': 'stop'/'left'/'right'/'forward'/'none', 
    #         #    'acc': ...
    #         # }
    #         detection = self.camera_manager.detect_obj_parameter('traffic_sign')
    #         # Implement how your camera_manager returns these fields

    #         if detection.get('traffic_sign_detected', False):
    #             sign_type = detection.get('traffic_sign_type', 'none')
    #             x = detection.get('x', 0)
    #             y = detection.get('y', 0)
    #             acc = detection.get('acc', 0)
    #             w = detection.get('w', 0)
    #             h = detection.get('h', 0)
                
    #             # ---------------------------------------------
    #             # Camera lock-on to center sign in frame
    #             # ---------------------------------------------
    #             x_offset_ratio = (x / camera_width) - 0.5
    #             target_x_angle = x_offset_ratio * 180  # scale up to ±90

    #             dx = target_x_angle - self.x_angle
    #             self.x_angle += 0.2 * dx  # Smooth movement factor
    #             self.x_angle = self.clamp_number(self.x_angle, self.PAN_MIN_ANGLE, self.PAN_MAX_ANGLE)
    #             self.px.set_cam_pan_angle(int(self.x_angle))

    #             y_offset_ratio = 0.5 - (y / camera_height)
    #             target_y_angle = y_offset_ratio * 130  # Scale to tilt range

    #             dy = target_y_angle - self.y_angle
    #             self.y_angle += 0.2 * dy  # Smooth movement factor
    #             self.y_angle = self.clamp_number(self.y_angle, self.TILT_MIN_ANGLE, self.TILT_MAX_ANGLE)
    #             self.px.set_cam_tilt_angle(int(self.y_angle))
                
    #             logger.debug(f"Traffic Sign => type={sign_type}, confidence={acc}, center=({x},{y}), size=({w},{h}), " + 
    #                          f"camera pan={self.x_angle:.1f}, tilt={self.y_angle:.1f}")
                
    #             # If you want to do something special on "stop", "left", etc.
    #             # e.g. if sign_type == 'stop': self.px.forward(0)
            
    #         time.sleep(0.05)

    #     logger.info("Traffic sign detection loop stopped.")
    
    # ------------------------------------------------------------------
    # YOLO Object Detection
    # ------------------------------------------------------------------    
    def load_yolo_model(self, model_path=None):
        """
        Load the YOLO model from the specified path.
        
        Args:
            model_path (str, optional): Path to the YOLO model file (.pt)
                                       If None, uses the default model in modules directory
        
        Returns:
            bool: True if model loaded successfully, False otherwise
        """
        try:
            # Use provided path or default to model.pt in modules directory
            if model_path is None:
                model_path = self.model_path
                
            if not os.path.exists(model_path):
                logger.error(f"Model path is invalid or model not found: {model_path}")
                return False
                
            # Import here to prevent errors if modules aren't available
            try:
                import cv2
                from ultralytics import YOLO
            except ImportError as e:
                logger.error(f"Required modules not installed: {e}")
                logger.error("Please install with: pip install ultralytics opencv-python")
                return False
                
            # Load the model
            self.yolo_model = YOLO(model_path, task='detect')
            logger.info(f"YOLO model loaded successfully from {model_path}")
            
            # Get the label map
            self.yolo_labels = self.yolo_model.names
            logger.info(f"Detected {len(self.yolo_labels)} classes in model")
            
            return True
            
        except Exception as e:
            logger.error(f"Error loading YOLO model: {e}")
            return False
    def start_traffic_sign_detection(self):
        self.start_yolo_detection()
    
    def stop_traffic_sign_detection(self):
        self.stop_yolo_detection()
        
    def calibrate_right_turn(self):
        """
        Run a test of the right turn function to verify it turns approximately 90 degrees.
        This is a standalone function that can be called independently of YOLO detection.
        """
        logger.info("Starting right turn calibration...")
        # Make sure any existing detection is stopped first
        was_active = self.yolo_detection_active
        if was_active:
            self.stop_yolo_detection()
            
        # Run the calibration
        threading.Thread(target=self._run_turn_calibration, daemon=True).start()
        return True

    def set_confidence_threshold(self, threshold):
        """
        Set the confidence threshold for displaying detected objects.
        
        Args:
            threshold (float): Value between 0.0 and 1.0
        """
        if 0.0 <= threshold <= 1.0:
            self.yolo_min_confidence = threshold
            logger.info(f"Object detection confidence threshold set to {threshold}")
        else:
            logger.warning(f"Invalid confidence threshold: {threshold}. Must be between 0.0 and 1.0")    
            
    def start_yolo_detection(self, model_path=None):
        """
        Starts YOLO object detection using the camera feed.
        
        Args:
            model_path (str, optional): Path to the YOLO model file. 
                                       If None, uses already loaded model or the default model.
        """
        if self.yolo_detection_active:
            logger.warning("YOLO object detection is already running!")
            return False
        
        # Load model if not already loaded
        if self.yolo_model is None:
            if not self.load_yolo_model(model_path):
                logger.error("Failed to load YOLO model.")
                return False
        
        logger.info("Starting YOLO object detection...")
        self.yolo_detection_active = True
        
        # Reset camera angles
        self.x_angle = 0
        self.y_angle = 0

        self.led_manager.turn_off()
        
        # Start the detection thread
        self.yolo_detection_thread = threading.Thread(
            target=self._run_async_detection_loop,
            daemon=True
        )
        self.yolo_detection_thread.start()
        
        return True
    
    def _run_async_detection_loop(self):
        """Run the async detection loop in its own event loop"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._yolo_detection_loop())
        finally:
            loop.close()
    def stop_yolo_detection(self):
        """
        Stops YOLO object detection.
        """
        if not self.yolo_detection_active:
            logger.warning("YOLO object detection is not currently running!")
            return False
        
        logger.info("Stopping YOLO object detection...")
        self.yolo_detection_active = False
        
        if self.yolo_detection_thread and self.yolo_detection_thread.is_alive():
            self.yolo_detection_thread.join(timeout=2.0)
        
        self.yolo_detection_thread = None
        self.yolo_results = []
        self.yolo_object_count = 0
        
        # Reset all state variables
        self.traffic_light_state = None
        self.traffic_light_detected = False
        self.waiting_for_green = False
        
        self.stop_sign_detected = False
        self.stop_sign_timer = None
        self.waiting_at_stop_sign = False
        
        self.right_turn_sign_detected = False
        self.right_turn_timer = None
        self.executing_right_turn = False

        # Stop any LED patterns
        self.stop_all_led_patterns()

        # Stop any continuous turn if it's active
        if hasattr(self, 'continuous_turning') and self.continuous_turning:
            self.stop_continuous_turn()

        # Disable drawing overlays
        try:
            self.camera_manager.disable_vilib_drawing()
        except Exception as e:
            logger.error(f"Error disabling vilib drawing: {e}")

        self.px.forward(0)  # Stop the robot
        return True
    
    async def _yolo_detection_loop(self):
        """
        Main loop for YOLO object detection.
        Continuously gets frames from camera, processes with YOLO model,
        and tracks detected objects.
        """
        logger.info("YOLO detection loop started.")
        
        try:
            import cv2
            import numpy as np
        except ImportError as e:
            logger.error(f"Required modules not installed: {e}")
            self.yolo_detection_active = False
            return
        
        # Reset camera position at start of detection loop
        self.x_angle = 0
        self.y_angle = 0
        self.px.set_cam_pan_angle(0)
        self.px.set_cam_tilt_angle(0)
        
        frame_rate_buffer = []
        fps_avg_len = 30
        avg_frame_rate = 0
        
        # Expected model input size for NCNN model - 480x480 is recommended for NCNN models
        model_input_size = (640, 640)
        
        while self.yolo_detection_active:
            try:
                t_start = time.perf_counter()
                
                # Get current frame from camera via camera_manager
                frame = self._get_camera_frame()
                
                # Skip if no frame is available
                if frame is None:
                    logger.warning("No frame available from camera.")
                    await asyncio.sleep(0.1)
                    continue
                
                # Convert frame format if needed
                if len(frame.shape) == 2:  # If grayscale
                    frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                
                # Resize frame to match the expected model input size
                # This is crucial for NCNN models which require exact input dimensions
                # Resize by cropping to maintain aspect ratio instead of stretching
                # First, calculate target aspect ratio
                target_aspect = model_input_size[0] / model_input_size[1]
                # Calculate current aspect ratio
                current_aspect = frame.shape[1] / frame.shape[0]
                  # Determine crop dimensions and store the offsets for coordinate correction later
                offset_x = 0
                offset_y = 0
                original_width = frame.shape[1]
                original_height = frame.shape[0]
                
                if current_aspect > target_aspect:
                    # Image is wider than needed - crop width
                    new_width = int(original_height * target_aspect)
                    offset_x = (original_width - new_width) // 2
                    # Crop horizontally to target aspect ratio
                    cropped = frame[:, offset_x:offset_x+new_width]
                    # Store the actual cropped dimensions
                    cropped_width = new_width
                    cropped_height = original_height
                else:
                    # Image is taller than needed - crop height
                    new_height = int(original_width / target_aspect)
                    offset_y = (original_height - new_height) // 2
                    # Crop vertically to target aspect ratio
                    cropped = frame[offset_y:offset_y+new_height, :]
                    # Store the actual cropped dimensions
                    cropped_width = original_width
                    cropped_height = new_height
                
                # Now resize the cropped image to the target size
                resized_frame = cv2.resize(cropped, model_input_size)
                
                # Store transformation parameters for later coordinate conversion
                self.transform_params = {
                    'offset_x': offset_x,
                    'offset_y': offset_y,
                    'cropped_width': cropped_width,
                    'cropped_height': cropped_height,
                    'model_width': model_input_size[0],
                    'model_height': model_input_size[1],
                    'original_width': original_width,
                    'original_height': original_height
                }
                
                # Run inference on resized frame
                results = self.yolo_model(resized_frame, verbose=False)
                
                # Extract results
                detections = results[0].boxes
                self.yolo_results = results  # Store for external access
                
                # Reset object count
                self.yolo_object_count = 0
                
                # Process detections and convert coordinates back to original image space
                transformed_detections = []
                
                # Process each detection
                for i in range(len(detections)):
                    # Get bounding box coordinates (convert from tensor)
                    xyxy_tensor = detections[i].xyxy.cpu()
                    xyxy = xyxy_tensor.numpy().squeeze()
                    xmin, ymin, xmax, ymax = xyxy.astype(int)
                    
                    # Get class ID, name and confidence
                    classidx = int(detections[i].cls.item())
                    classname = self.yolo_labels[classidx]
                    conf = detections[i].conf.item()
                    
                    # Skip if below confidence threshold
                    if conf < self.yolo_min_confidence:
                        continue
                    
                    # Convert coordinates from model space to original image space
                    # First, convert from model space to cropped space
                    cropped_xmin = int(xmin * (self.transform_params['cropped_width'] / self.transform_params['model_width']))
                    cropped_ymin = int(ymin * (self.transform_params['cropped_height'] / self.transform_params['model_height']))
                    cropped_xmax = int(xmax * (self.transform_params['cropped_width'] / self.transform_params['model_width']))
                    cropped_ymax = int(ymax * (self.transform_params['cropped_height'] / self.transform_params['model_height']))
                    
                    # Then add the offset to get to original image space
                    orig_xmin = cropped_xmin + self.transform_params['offset_x']
                    orig_ymin = cropped_ymin + self.transform_params['offset_y']
                    orig_xmax = cropped_xmax + self.transform_params['offset_x']
                    orig_ymax = cropped_ymax + self.transform_params['offset_y']
                    
                    # Ensure coordinates are within image boundaries
                    orig_xmin = max(0, min(orig_xmin, original_width - 1))
                    orig_xmax = max(0, min(orig_xmax, original_width - 1))
                    orig_ymin = max(0, min(orig_ymin, original_height - 1))
                    orig_ymax = max(0, min(orig_ymax, original_height - 1))
                    
                    # Calculate width, height, and center
                    width = orig_xmax - orig_xmin
                    height = orig_ymax - orig_ymin
                    center_x = (orig_xmin + orig_xmax) // 2
                    center_y = (orig_ymin + orig_ymax) // 2
                    
                    # Create object info dictionary with original image coordinates
                    object_info = {
                        'class': classname,
                        'confidence': conf,
                        'x': center_x,
                        'y': center_y,
                        'width': width,
                        'height': height,
                        'xmin': orig_xmin,
                        'ymin': orig_ymin,
                        'xmax': orig_xmax,
                        'ymax': orig_ymax
                    }
                    
                    # Count objects above confidence threshold
                    self.yolo_object_count += 1
                    
                    # Calculate distance for this object
                    distance_cm = self.calculate_object_distance(object_info)
                    if distance_cm is not None:
                        object_info['distance_cm'] = distance_cm
                        logger.debug(f"Object {classname}: estimated distance {distance_cm:.1f} cm")
                    
                    # Add to transformed detections
                    transformed_detections.append(object_info)
                
                # Display detections with corrected coordinates on vilib camera feed
                self.camera_manager.display_yolo_detections_on_vilib(transformed_detections, self.yolo_labels, self.yolo_min_confidence)
                
                # Find objects to track - modified to find the closest object
                closest_object = None
                min_distance = float('inf')
                traffic_light_object = None
                stop_sign_object = None
                right_turn_object = None
                
                # Sort detections by distance
                sorted_detections = sorted(
                    [obj for obj in transformed_detections if 'distance_cm' in obj],
                    key=lambda x: x['distance_cm']
                )
                
                # Filter out objects in ignore periods
                current_time = time.time()
                filtered_detections = []
                for obj in sorted_detections:
                    # Skip traffic lights in ignore period
                    if obj['class'] in ["Rouge", "Vert", "Orange"] and current_time < self.ignore_traffic_lights_until:
                        logger.debug(f"Skipping tracking of {obj['class']} (in ignore period)")
                        continue
                    # Skip stop signs in ignore period
                    elif obj['class'] == "Stop" and current_time < self.ignore_stop_signs_until:
                        logger.debug(f"Skipping tracking of {obj['class']} (in ignore period)")
                        continue
                    # Skip right turn signs if a turn is pending or executing
                    elif obj['class'] == "Tourner" and (self.right_turn_pending or self.executing_right_turn):
                        logger.debug(f"Skipping tracking of {obj['class']} (turn pending or executing)")
                        continue
                    # If not filtered, add to our filtered detections
                    filtered_detections.append(obj)
                
                # First process the closest object from filtered detections
                if filtered_detections:
                    closest_object = filtered_detections[0]
                    min_distance = filtered_detections[0]['distance_cm']
                    logger.info(f"Closest object: {closest_object['class']} at {min_distance:.1f} cm")
                    
                    # Check if closest object is a traffic light, stop sign, or turn sign
                    if closest_object['class'] in ["Rouge", "Vert", "Orange"]:
                        traffic_light_object = closest_object
                    elif closest_object['class'] == "Stop":
                        stop_sign_object = closest_object
                    elif closest_object['class'] == "Tourner":
                        right_turn_object = closest_object

                # Priority of handling:
                # 1. Traffic lights (highest priority)
                # 2. Stop signs
                # 3. Right turn signs
                
                # Handle traffic light detection and behavior
                if traffic_light_object:
                    await self._handle_traffic_light(traffic_light_object['class'], traffic_light_object)
                    # Traffic lights take priority for tracking
                    best_object = traffic_light_object
                # Handle stop sign if detected and not currently waiting for green at a traffic light
                elif stop_sign_object and not self.waiting_for_green:
                    await self._handle_stop_sign(stop_sign_object)
                    best_object = stop_sign_object
                # Handle right turn sign if detected and not handling traffic light or stop sign
                elif right_turn_object and not self.waiting_for_green and not self.waiting_at_stop_sign:
                    await self._handle_right_turn_sign(right_turn_object)
                    best_object = right_turn_object
                # If no priority objects detected and we're not waiting for anything
                elif not (self.waiting_for_green or self.waiting_at_stop_sign or self.executing_right_turn):
                    # Move forward at default speed
                    self.px.forward(1)  # 1% speed
                    # Use closest object for tracking regardless of type
                    best_object = closest_object
                
                # Check for pending right turn (even if no sign is visible anymore)
                if self.right_turn_pending and time.time() >= self.right_turn_timer:
                    await self._execute_right_turn()
                    # Skip object tracking during this frame since we're executing a turn
                    best_object = None
                
                # Track the best detected object with the camera
                if best_object:
                    self._track_detected_object(best_object)
                
                # Calculate FPS
                t_stop = time.perf_counter()
                frame_rate_calc = 1 / (t_stop - t_start)
                
                # Update FPS buffer for average calculation
                if len(frame_rate_buffer) >= fps_avg_len:
                    frame_rate_buffer.pop(0)
                frame_rate_buffer.append(frame_rate_calc)
                  # Calculate average FPS
                avg_frame_rate = np.mean(frame_rate_buffer)
                
                # Print detected objects to standard output
                if self.yolo_object_count > 0:
                    objects_info = []
                    for obj in transformed_detections:
                        objects_info.append(f"{obj['class']} ({obj['confidence']:.2f})")
                    
                    logger.info(f"Detected objects: {', '.join(objects_info)}")
                
                logger.info(f"YOLO detection: {self.yolo_object_count} objects, FPS: {avg_frame_rate:.1f}")
                
            except Exception as e:
                logger.error(f"Error in YOLO detection loop: {e}")
                await asyncio.sleep(0.1)
        
        # Reset camera position at end of detection loop
        self.x_angle = 0
        self.y_angle = 0
        self.px.set_cam_pan_angle(0)
        self.px.set_cam_tilt_angle(0)
        
        logger.info("YOLO detection loop stopped.")
    
    def _get_camera_frame(self):
        """
        Get the current frame from the camera via vilib.
        
        Returns:
            numpy.ndarray: The current camera frame or None if not available
        """
        try:
            # First try to use camera_manager's method if available
            if hasattr(self.camera_manager, '_get_current_frame'):
                return self.camera_manager._get_current_frame()
            
            # Fallback to direct vilib access
            try:
                from vilib import Vilib
                if hasattr(Vilib, 'img') and Vilib.img is not None:
                    import numpy as np
                    return np.array(Vilib.img).copy()
            except (ImportError, Exception) as e:
                logger.error(f"Error accessing vilib: {e}")
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting camera frame: {e}")
            return None
    
    def _track_detected_object(self, object_info):
        """
        Track a detected object by adjusting camera pan/tilt.
        Avoids micro-adjustments to reduce servo jitter.
        
        Args:
            object_info (dict): Object detection info including x, y coordinates
        """
        x, y = object_info['x'], object_info['y']
        
        # Calculate offset from center of frame
        x_offset_ratio = (x / self.camera_width) - 0.5
        target_x_angle = x_offset_ratio * 180  # Scale to ±90°
        
        # Only make adjustment if the change is significant (> 3 degrees)
        dx = target_x_angle - self.x_angle
        if abs(dx) > 3.0:
            self.x_angle += 0.2 * dx  # Smooth movement factor
            self.x_angle = self.clamp_number(self.x_angle, self.PAN_MIN_ANGLE, self.PAN_MAX_ANGLE)
            self.px.set_cam_pan_angle(int(self.x_angle))
        
        y_offset_ratio = 0.5 - (y / self.camera_height)
        target_y_angle = y_offset_ratio * 130  # Scale to tilt range
        
        # Only make adjustment if the change is significant (> 3 degrees)
        dy = target_y_angle - self.y_angle
        if abs(dy) > 3.0:
            self.y_angle += 0.2 * dy  # Smooth movement factor
            self.y_angle = self.clamp_number(self.y_angle, self.TILT_MIN_ANGLE, self.TILT_MAX_ANGLE)
            self.px.set_cam_tilt_angle(int(self.y_angle))
        
        logger.debug(
            f"Tracking {object_info['class']} at ({x},{y}), "
            f"distance: {object_info.get('distance_cm', 'unknown'):.1f} cm, "
            f"camera pan={self.x_angle:.1f}, tilt={self.y_angle:.1f}"
        )
    
    async def _handle_traffic_light(self, class_name, object_info):
        """
        Handle traffic light detection and corresponding robot behavior.
        Now uses distance in cm for decision making.
        
        Args:
            class_name (str): The detected class name ("Rouge", "Vert", or "Orange")
            object_info (dict): Object information with coordinates, size, etc.
        """
        # If we're in the ignore period, skip processing traffic lights
        if time.time() < self.ignore_traffic_lights_until:
            logger.info(f"Ignoring traffic light {class_name} (in ignore period)")
            return
            
        # If it's not a traffic light, reset if we were previously tracking one
        if class_name not in ["Rouge", "Vert", "Orange"]:
            if self.traffic_light_detected:
                logger.info("Lost track of traffic light")
                self.traffic_light_detected = False
                self.traffic_light_state = None
            return
        
        # Get calculated distance if available
        distance_cm = object_info.get('distance_cm')
        
        # Determine if object is close enough based on distance in cm
        if distance_cm is not None:
            is_close_enough = distance_cm < self.distance_threshold_cm
            distance_info = f"distance: {distance_cm:.1f} cm"
        else:
            # Fallback to relative size if distance unavailable
            relative_size = (object_info['width'] * object_info['height']) / (self.camera_width * self.camera_height)
            is_close_enough = relative_size > self.traffic_light_distance_threshold
            distance_info = f"relative size: {relative_size:.2f}"
        
        # Update traffic light state
        prev_state = self.traffic_light_state
        self.traffic_light_state = class_name
        self.traffic_light_detected = True
        
        # Log detection
        if is_close_enough:
            logger.info(f"Traffic light {class_name} detected and is close enough ({distance_info})")
        else:
            logger.info(f"Traffic light {class_name} detected but not close enough yet ({distance_info})")
        
        # Handle traffic light behavior
        if is_close_enough:
            # Handle red and yellow lights (both require stopping)
            if class_name in ["Rouge", "Orange"] and (prev_state not in ["Rouge", "Orange"] or not self.waiting_for_green):
                # Red or Yellow light - stop and announce
                self.px.forward(0)
                self.waiting_for_green = True
                
                # Turn on LED for stop
                self.start_stop_light()
                
                # Announce if TTS manager is available
                if self.tts_manager:
                    await self.tts_manager.say(f"{class_name.capitalize()} light detected", priority=1)
                
                logger.info(f"{class_name.upper()} LIGHT - Stopping robot")
                
            elif class_name == "Vert":
                # If detecting green when close and not waiting for green, reset camera position
                if not self.waiting_for_green:
                    # Reset camera position when detecting green light
                    self.x_angle = 0
                    self.y_angle = 0
                    self.px.set_cam_pan_angle(0)
                    self.px.set_cam_tilt_angle(0)
                    
                if self.waiting_for_green:
                    # We were waiting for green after seeing red/yellow, now proceed
                    self.px.forward(1)  # 1% speed
                    self.waiting_for_green = False
                    
                    # Turn off stop light
                    self.stop_all_led_patterns(False)
                    
                    # Reset camera position after green light
                    self.x_angle = 0
                    self.y_angle = 0
                    self.px.set_cam_pan_angle(0)
                    self.px.set_cam_tilt_angle(0)
                    
                    # Set ignore period for 3 seconds
                    self.ignore_traffic_lights_until = time.time() + 3.0
                    logger.info("Setting traffic light ignore period for 3 seconds")
                    
                    # Announce if TTS manager is available
                    if self.tts_manager:
                        await self.tts_manager.say("Green light detected", priority=1)
                    
                    logger.info("GREEN LIGHT after stopping - Proceeding at 1% speed")
                elif prev_state != "Vert":
                    # Green light from no previous light detected
                    self.px.forward(1)  # 1% speed
                    
                    # Turn off any LED patterns
                    self.stop_all_led_patterns(False)

                    # Announce if TTS manager is available
                    if self.tts_manager:
                        await self.tts_manager.say("Green light detected", priority=1)

                    logger.info("GREEN LIGHT - Proceeding at 1% speed")
        elif not self.waiting_for_green:
            # If not close enough and not waiting for green after red/yellow, move forward
            self.px.forward(1)  # 1% speed
            logger.info("Traffic light not close enough, proceeding at 1% speed")
            
    async def _handle_stop_sign(self, object_info):
        """
        Handle stop sign detection and corresponding robot behavior.
        Now uses distance in cm for decision making.
        
        Args:
            object_info (dict): Object information with coordinates, size, etc.
        """
        # If we're in the ignore period, skip processing stop signs
        if time.time() < self.ignore_stop_signs_until:
            logger.info("Ignoring stop sign detection (in ignore period)")
            return
            
        # Get calculated distance in cm
        distance_cm = object_info.get('distance_cm')
        
        # Determine if object is close enough based on distance in cm
        if distance_cm is not None:
            is_close_enough = distance_cm < self.distance_threshold_cm
            distance_info = f"distance: {distance_cm:.1f} cm"
        else:
            # Fallback to relative size if distance unavailable
            relative_size = (object_info['width'] * object_info['height']) / (self.camera_width * self.camera_height)
            is_close_enough = relative_size > self.traffic_light_distance_threshold
            distance_info = f"relative size: {relative_size:.2f}"
        
        # Update stop sign state
        self.stop_sign_detected = True
        
        # Log detection
        if is_close_enough:
            logger.info(f"Stop sign detected and is close enough ({distance_info})")
        else:
            logger.info(f"Stop sign detected but not close enough yet ({distance_info})")
        
        # Handle stop sign behavior
        if is_close_enough and not self.waiting_at_stop_sign:
            # Stop sign is close enough - stop for 2 seconds
            self.px.forward(0)
            self.waiting_at_stop_sign = True
            
            # Turn on LED for stop
            self.start_stop_light()
            
            # Announce if TTS manager is available
            if self.tts_manager:
                await self.tts_manager.say("Stop sign detected", priority=1)
            
            logger.info("STOP SIGN - Stopping robot for 2 seconds")
            
            # Start timer to resume after 2 seconds
            self.stop_sign_timer = time.time()
            
        elif self.waiting_at_stop_sign:
            # Check if we've waited long enough (2 seconds)
            if time.time() - self.stop_sign_timer >= 2.0:
                # Resume movement
                self.px.forward(1)  # 1% speed
                self.waiting_at_stop_sign = False
                
                # Turn off stop light
                self.stop_all_led_patterns(False)
                
                # Reset camera position after stopping at stop sign
                self.x_angle = 0
                self.y_angle = 0
                self.px.set_cam_pan_angle(0)
                self.px.set_cam_tilt_angle(0)
                
                # Set ignore period for 3 seconds
                self.ignore_stop_signs_until = time.time() + 3.0
                logger.info("Setting stop sign ignore period for 3 seconds")

                # Announce if TTS manager is available
                if self.tts_manager:
                    await self.tts_manager.say("Proceeding after stop", priority=1)
                
                logger.info("STOP SIGN - Waited 2 seconds, now proceeding at 1% speed")
        elif not self.waiting_at_stop_sign:
            # Not close enough yet, continue moving forward
            self.px.forward(1)  # 1% speed
            logger.info("Stop sign detected but not close enough, proceeding at 1% speed")
    
    async def _handle_right_turn_sign(self, object_info):
        """
        Handle right turn sign detection and corresponding robot behavior.
        Now uses distance in cm for decision making.
        
        Args:
            object_info (dict): Object information with coordinates, size, etc.
        """
        # If we're already executing a right turn, don't process any new detections
        if self.executing_right_turn:
            return
            
        # If we already have a pending turn, don't process new turn sign detection
        if self.right_turn_pending:
            return
        
        # Get calculated distance in cm
        distance_cm = object_info.get('distance_cm')
        
        # Determine if object is close enough based on distance in cm
        if distance_cm is not None:
            is_close_enough = distance_cm < self.distance_threshold_cm
            distance_info = f"distance: {distance_cm:.1f} cm"
        else:
            # Fallback to relative size if distance unavailable
            relative_size = (object_info['width'] * object_info['height']) / (self.camera_width * self.camera_height)
            is_close_enough = relative_size > self.traffic_light_distance_threshold
            distance_info = f"relative size: {relative_size:.2f}"
        
        # Update right turn sign state
        self.right_turn_sign_detected = True
        
        # Log detection
        if is_close_enough:
            logger.info(f"Right turn sign detected and is close enough ({distance_info})")
        else:
            logger.info(f"Right turn sign detected but not close enough yet ({distance_info})")
        
        # Handle right turn sign behavior
        if is_close_enough and not self.executing_right_turn and not self.right_turn_pending:
            # Right turn sign is close enough - prepare to turn in 3 seconds
            logger.info("RIGHT TURN SIGN - Will turn right in 3 seconds")
            
            # Set the flag to indicate a pending turn
            self.right_turn_pending = True
            
            # Start timer to execute turn after 3 seconds
            self.right_turn_timer = time.time() + 5.0
            
            # Announce if TTS manager is available
            if self.tts_manager:
                await self.tts_manager.say("Right turn ahead", priority=1)
        
        elif not is_close_enough and not self.right_turn_pending:
            # Not close enough yet, continue moving forward
            self.px.forward(1)  # 1% speed
            logger.info("Right turn sign detected but not close enough, proceeding at 1% speed")
            
    async def _execute_right_turn(self):
        """
        Execute the right turn. Called when it's time to turn after seeing a right turn sign.
        """
        # Execute right turn
        self.executing_right_turn = True
        self.right_turn_pending = False
        
        # Start turn signal LED blinking
        self.start_turn_signal_blink()
        
        # Announce the turn
        if self.tts_manager:
            await self.tts_manager.say("Turning right", priority=1)
        
        logger.info("RIGHT TURN SIGN - Executing right turn now")
        # Stop forward movement before starting the turn
        self.px.forward(0)
        
        # Setup for differential steering
        speed_value = 0.1  # 10% speed
        turn_value = 1.0   # Full right turn (normalized -1 to 1)
        turn_direction = 1  # 1 for right, -1 for left, 0 for straight
        abs_turn = abs(turn_value)  # Absolute turn value
        
        # Differential steering: Reduce speed of inner wheel based on turn amount
        turn_factor = abs_turn * 0.9  # How much to reduce inner wheel speed (max 90% reduction)
        
        # Calculate per-wheel speeds
        if turn_direction > 0:  # Turning right
            left_speed = speed_value  # Outer wheel at full speed
            right_speed = speed_value * (1 - turn_factor)  # Inner wheel slowed
        else:  # Turning left or straight
            left_speed = speed_value * (1 - (turn_factor if turn_direction < 0 else 0))  # Inner wheel slowed if turning left
            right_speed = speed_value  # Outer wheel at full speed
        
        # Apply speeds to motors and set steering angle
        logger.info(f"Turning right - Left motor: {left_speed * 100:.1f}%, Right motor: {right_speed * 100:.1f}%, Steering angle: 35°")
        self.px.set_motor_speed(1, left_speed * 100)    # Left motor
        self.px.set_motor_speed(2, -right_speed * 100)  # Right motor (reversed in hardware)
        self.px.set_dir_servo_angle(35)    # Set steering to full right turn
        
        # Wait for the turn to complete
        logger.info("Executing right turn seconds...")
        await asyncio.sleep(self.right_turn_time)  # Wait for the turn time (default 2 seconds)
        
        # Reset direction and return to normal driving
        logger.info("Turn completed, resetting steering angle")
        self.px.set_dir_servo_angle(0)
        self.px.set_motor_speed(1, 1)  # Return to normal forward speed (1%)
        self.px.set_motor_speed(2, -1) # Return to normal forward speed (1%)
        
        # Reset turn state
        self.right_turn_timer = None
        self.executing_right_turn = False
        self.right_turn_sign_detected = False

        # Stop LED blinking
        self.stop_all_led_patterns(False)
        
        # Reset camera position after turning right
        self.x_angle = 0
        self.y_angle = 0
        self.px.set_cam_pan_angle(0)
        self.px.set_cam_tilt_angle(0)

        # Move forward slowly after the turn
        self.px.forward(1)  # 1% speed
        
        logger.info("RIGHT TURN SIGN - Turn completed, continuing forward")

    def _run_turn_calibration(self):
        """Run a single right turn to calibrate the turning parameters"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            logger.info("Starting turn calibration test...")
            
            # Execute the test turn function
            loop.run_until_complete(self._test_right_turn())
            
            logger.info("Turn calibration completed.")
            
        except Exception as e:
            logger.error(f"Error in turn calibration: {e}")
        finally:
            loop.close()
    
    async def _test_right_turn(self):
        """Test function to execute a single right turn"""
        try:
            logger.info("----- RIGHT TURN CALIBRATION TEST -----")
            logger.info("Testing if the robot turns 90 degrees with current settings")
            
            # Announce the test if TTS is available
            if self.tts_manager:
                await self.tts_manager.say("Testing right turn calibration", priority=1)
            
            # Make sure we're stopped
            self.px.forward(0)
            await asyncio.sleep(1.0)
            
            # Start turn signal LED blinking
            self.start_turn_signal_blink()
            
            # Execute the turn
            logger.info("Executing right turn now...")
            
            # Setup for differential steering
            speed_value = 0.1  # 10% speed
            turn_value = 1.0   # Full right turn (normalized -1 to 1)
            turn_direction = 1  # 1 for right, -1 for left, 0 for straight
            abs_turn = abs(turn_value)  # Absolute turn value
            
            # Differential steering: Reduce speed of inner wheel based on turn amount
            turn_factor = abs_turn * 0.9  # How much to reduce inner wheel speed (max 90% reduction)
            
            # Calculate per-wheel speeds
            if turn_direction > 0:  # Turning right
                left_speed = speed_value  # Outer wheel at full speed
                right_speed = speed_value * (1 - turn_factor)  # Inner wheel slowed
            else:  # Turning left or straight
                left_speed = speed_value * (1 - (turn_factor if turn_direction < 0 else 0))  # Inner wheel slowed if turning left
                right_speed = speed_value  # Outer wheel at full speed
            
            # Apply speeds to motors and set steering angle
            self.px.set_motor_speed(1, left_speed * 100)    # Left motor
            self.px.set_motor_speed(2, -right_speed * 100)  # Right motor (reversed in hardware)
            self.px.set_dir_servo_angle(35)    # Set steering to full right turn
            
            # Wait for the turn to complete
            logger.info("Turning right for 2 seconds...")
            await asyncio.sleep(self.right_turn_time)  # Wait for the turn time (default 2 seconds)
            
            # Stop and reset direction
            self.px.set_motor_speed(1, 0)
            self.px.set_motor_speed(2, 0)
            self.px.set_dir_servo_angle(0)
            self.px.forward(0)
            
            # Stop LED blinking
            self.stop_all_led_patterns()
            
            logger.info("Calibration turn completed")
            
            # Announce completion if TTS is available
            if self.tts_manager:
                await self.tts_manager.say("Turn calibration completed", priority=1)

            logger.info(f"Check if the robot turned approximately 90 degrees in {self.right_turn_time} seconds.")
            logger.info("If not, adjust the turn parameters in _handle_right_turn_sign method.")
            logger.info("----- END OF CALIBRATION TEST -----")
            
        except Exception as e:
            logger.error(f"Error in right turn test: {e}")
            # Stop the robot if there was an error
            self.px.forward(0)
            self.px.set_dir_servo_angle(0)
            
            # Make sure to stop LED blinking
            self.stop_all_led_patterns()
    
    def set_distance_threshold(self, distance):
        """
        Set the distance threshold for detecting objects.
        
        Args:
            distance (float): Distance in pixels
        """
        if distance > 0:
            self.traffic_light_distance_threshold = distance
            logger.info(f"Distance threshold set to {distance} pixels")
        else:
            logger.warning(f"Invalid distance threshold: {distance}. Must be greater than 0")

    def set_turn_time(self, time):
        """
        Set the time duration for executing a right turn.
        
        Args:
            time (float): Time in seconds
        """
        if time > 0:
            self.right_turn_time = time
            logger.info(f"Right turn time set to {time} seconds")
        else:
            logger.warning(f"Invalid right turn time: {time}. Must be greater than 0")
    def set_right_turn_time(self, seconds):
        """
        Set the duration for a right turn when turning automatically.
        
        Args:
            seconds (float): Time in seconds for the turn duration
            
        Returns:
            float: The updated turn time value
        """
        if seconds > 0:
            self.right_turn_time = seconds
            logger.info(f"Right turn time set to {seconds} seconds")
        else:
            logger.warning(f"Invalid turn time: {seconds}. Must be positive.")
        
        return self.right_turn_time
        
    def get_right_turn_time(self):
        """
        Get the current duration setting for right turns.
        
        Returns:
            float: Current turn time in seconds
        """
        return self.right_turn_time
    
    async def start_continuous_right_turn(self, speed_value=0.1):
        """
        Start a continuous right turn using differential steering.
        The turn will continue until stop_continuous_turn() is called.
        
        Args:
            speed_value (float): Base speed value (0.0-1.0) for the turn
            
        Returns:
            bool: True if turn started successfully
        """
        try:
            # Make sure we're not already turning
            if hasattr(self, 'continuous_turning') and self.continuous_turning:
                logger.warning("Already performing a continuous turn")
                return False
                
            logger.info("Starting continuous right turn...")
            
            # Set turning flag
            self.continuous_turning = True
            
            # Start turn signal LED blinking
            self.start_turn_signal_blink()
            
            # Stop forward movement before starting the turn
            self.px.forward(0)
            
            # Setup for differential steering
            turn_value = 1.0   # Full right turn (normalized -1 to 1)
            turn_direction = 1  # 1 for right, -1 for left, 0 for straight
            abs_turn = abs(turn_value)  # Absolute turn value
            
            # Differential steering: Reduce speed of inner wheel based on turn amount
            turn_factor = abs_turn * 0.9  # How much to reduce inner wheel speed (max 90% reduction)
            
            # Calculate per-wheel speeds
            if turn_direction > 0:  # Turning right
                left_speed = speed_value  # Outer wheel at full speed
                right_speed = speed_value * (1 - turn_factor)  # Inner wheel slowed
            else:  # Turning left or straight
                left_speed = speed_value * (1 - (turn_factor if turn_direction < 0 else 0))  # Inner wheel slowed if turning left
                right_speed = speed_value  # Outer wheel at full speed
            
            # Apply speeds to motors and set steering angle
            logger.info(f"Continuous turning right - Left motor: {left_speed * 100:.1f}%, Right motor: {right_speed * 100:.1f}%, Steering angle: 35°")
            self.px.set_motor_speed(1, left_speed * 100)    # Left motor
            self.px.set_motor_speed(2, -right_speed * 100)  # Right motor (reversed in hardware)
            self.px.set_dir_servo_angle(35)    # Set steering to full right turn
            
            logger.info("Continuous right turn active - call stop_continuous_turn() to stop")
            
            # Announce if TTS manager is available
            if self.tts_manager:
                asyncio.create_task(self.tts_manager.say("Starting continuous right turn", priority=1))
                
            return True
            
        except Exception as e:
            logger.error(f"Error starting continuous turn: {e}")
            # Make sure motors are stopped if there's an error
            self.px.forward(0)
            self.px.set_dir_servo_angle(0)
            self.continuous_turning = False
            
            # Stop LED blinking
            self.stop_all_led_patterns()
            
            return False
            
    def stop_continuous_turn(self):
        """
        Stop the continuous turn that was started with start_continuous_right_turn().
        Also resets steering angle and returns to normal driving mode.
        
        Returns:
            bool: True if successfully stopped, False if no turn was active
        """
        if not hasattr(self, 'continuous_turning') or not self.continuous_turning:
            logger.warning("No continuous turn currently active")
            return False
            
        logger.info("Stopping continuous turn and resetting steering")
        
        # Stop motors
        self.px.set_motor_speed(1, 0)
        self.px.set_motor_speed(2, 0)
        
        # Reset direction
        self.px.set_dir_servo_angle(0)
        
        # Reset continuous turning flag
        self.continuous_turning = False
        
        # Stop LED blinking
        self.stop_all_led_patterns()
        
        # Announce if TTS manager is available
        if self.tts_manager:
            # Use create_task to avoid blocking since this isn't an async method
            asyncio.create_task(self.tts_manager.say("Turn stopped", priority=1))
            
        logger.info("Continuous turn stopped")
        return True
    
    async def calibrate_right_turn_interactive(self, command="start", turn_time=None, speed=None):
        """
        Interactive calibration for the right turn.
        This function can be used to start/stop turns and adjust parameters.
        
        Args:
            command (str): Command to execute:
                           "start" - Start continuous turning
                           "stop" - Stop continuous turning
                           "test" - Run a single test turn with current parameters
                           "set_time" - Set the turn time
                           "set_speed" - Set the turning speed
            turn_time (float, optional): New turn time in seconds (for "set_time" command)
            speed (float, optional): New speed value 0.0-1.0 (for "set_speed" command)
            
        Returns:
            dict: Status and current settings
        """
        try:
            result = {
                "status": "success",
                "current_settings": {
                    "turn_time": self.right_turn_time,
                    "continuous_turning": hasattr(self, 'continuous_turning') and self.continuous_turning
                }
            }
            
            # Process the command
            if command == "start":
                # Default speed if not provided
                if speed is None:
                    speed = 0.1

                # Start a continuous turn
                turn_started = await self.start_continuous_right_turn(speed_value=speed)

                result["action"] = "Started continuous turn"
                result["continuous_turning"] = turn_started
                
            elif command == "stop":
                # Stop the continuous turn
                stopped = self.stop_continuous_turn()
                result["action"] = "Stopped continuous turn"
                result["continuous_turning"] = not stopped
                
            elif command == "test":
                # Run a single test turn with current settings
                logger.info(f"Running test turn with duration: {self.right_turn_time} seconds")
                
                # Start thread for calibration
                threading.Thread(target=self._run_turn_calibration, daemon=True).start()
                result["action"] = f"Running test turn for {self.right_turn_time} seconds"
                
            elif command == "set_time":
                if turn_time is not None and turn_time > 0:
                    old_time = self.right_turn_time
                    self.right_turn_time = turn_time
                    result["action"] = f"Changed turn time from {old_time} to {turn_time} seconds"
                    result["current_settings"]["turn_time"] = turn_time
                else:
                    result["status"] = "error"
                    result["error"] = "Invalid turn time provided"
                    
            elif command == "set_speed":
                if speed is not None and 0 < speed <= 1.0:
                    result["action"] = f"Updated turn speed to {speed}"
                    # If turning is active, restart with new speed
                    if hasattr(self, 'continuous_turning') and self.continuous_turning:
                        self.stop_continuous_turn()
                        # Start with new speed
                        turn_started = await self.start_continuous_right_turn(speed_value=speed)
                        result["continuous_turning"] = turn_started
                else:
                    result["status"] = "error"
                    result["error"] = "Invalid speed provided"
            else:
                result["status"] = "error"
                result["error"] = f"Unknown command: {command}"
                
            return result
            
        except Exception as e:
            logger.error(f"Error in calibration: {e}")
            return {
                "status": "error",
                "error": str(e),
                "current_settings": {
                    "turn_time": self.right_turn_time,
                    "continuous_turning": hasattr(self, 'continuous_turning') and self.continuous_turning
                }
            }
        
    def change_camera_resolution(self, width, height):
        """
        Change the camera resolution.
        
        Args:
            width (int): New width for the camera
            height (int): New height for the camera
        """
        self.camera_width = width
        self.camera_height = height

    # ------------------------------------------------------------------
    # LED Control Helpers 
    # ------------------------------------------------------------------
    def _start_blink_thread(self, times=0, interval=0.5, pattern_name="default"):
        """
        Start a non-blocking LED blink in a separate thread with a specific pattern.
        This method now uses the LED manager's built-in non-blocking functionality.
        
        Args:
            times (int): Number of blinks (ignored, always uses continuous blink)
            interval (float): Time between blinks in seconds
            pattern_name (str): Name to identify this blink pattern
        """
        # We now use the LEDManager's non-blocking blink functionality
        try:
            # Store the pattern name for debugging/reference
            self.led_blink_pattern = pattern_name
            
            # Start blinking using the LED manager
            self.led_manager.start_blinking(interval)
            logger.debug(f"Started LED blink pattern: {pattern_name} with interval {interval}s")
        except Exception as e:
            logger.error(f"Error starting LED blink pattern: {e}")
    
    def _stop_blink_thread(self, let_turned_on=True):
        """Stop any active LED blinking thread"""
        try:
            # Use the LED manager's stop_blinking method
            self.led_manager.stop_blinking(let_turned_on)
            self.led_blink_pattern = None
            logger.debug("Stopped LED blinking")
        except Exception as e:
            logger.error(f"Error stopping LED blink: {e}")
    
    def start_turn_signal_blink(self):
        """Start rapid blinking pattern for turn signals"""
        self._start_blink_thread(interval=0.25, pattern_name="turn_signal")
        
    def start_stop_light(self):
        """Turn on LED solid for stop indication"""
        try:
            # First stop any existing blinking
            self._stop_blink_thread(False)

            # Then turn on the LED solid
            self.led_manager.turn_on()
            self.led_blink_pattern = "stop_light"
            logger.debug("LED turned on solid for stop light")
        except Exception as e:
            logger.error(f"Error turning on stop light: {e}")
        
    def start_tracking_pulse(self):
        """Start slow pulsing pattern for tracking mode"""
        self._start_blink_thread(interval=0.75, pattern_name="tracking")
    
    def stop_all_led_patterns(self, let_turned_on=True):
        """Stop all LED patterns and turn LED off"""
        self._stop_blink_thread(let_turned_on)
        
    def calculate_distance(self, object_height_pixels, real_height_mm):
        """
        Calculate the distance to an object using the pinhole camera model.
        
        Args:
            object_height_pixels (float): Height of the object in pixels
            real_height_mm (float): Real-world height of the object in millimeters
        
        Returns:
            float: Distance to the object in centimeters
        """
        # Camera parameters (from the provided specs)
        # Focal length in mm
        focal_length_mm = 2.8  
        # Sensor height in mm calculated from specs
        sensor_height_mm = 2.7384  # From specs: image area height is 2738.4 μm
        # Total pixel height of the sensor
        sensor_pixel_height = self.camera_height  # Height of frame in pixels
        
        # Calculate the physical height on the sensor (similar triangles)
        # Formula: h_i = (p / P_s) * H_s
        physical_height_mm = (object_height_pixels / sensor_pixel_height) * sensor_height_mm
        
        # Calculate distance using pinhole model: Z = (f * H_0) / h_i
        distance_mm = (focal_length_mm * real_height_mm) / physical_height_mm
        
        # Convert to centimeters for easier readability
        distance_cm = distance_mm / 10.0
        
        return distance_cm
    
    def calculate_object_distance(self, object_info):
        """
        Calculate the distance to a detected object based on its type.
        
        Args:
            object_info (dict): Object information with height in pixels
                                and class/type information
        
        Returns:
            float: Distance to the object in centimeters
        """
        object_class = object_info.get('class', '')
        object_height_pixels = object_info.get('height', 0)
        
        # Skip calculation if no valid height
        if object_height_pixels <= 0:
            return None
        
        # Define real-world heights for different objects (in mm)
        if object_class in ["Rouge", "Vert", "Orange"]:
            # Traffic light (8cm = 80mm)
            real_height_mm = 80
        elif object_class == "Stop":
            # Stop sign (7cm = 70mm)
            real_height_mm = 70
        elif object_class == "Tourner":
            # Turn sign (7cm = 70mm)
            real_height_mm = 70
        else:
            # Default height for unknown objects (use 10cm as fallback)
            real_height_mm = 100
        
        # Calculate the distance
        distance_cm = self.calculate_distance(object_height_pixels, real_height_mm)
        
        return distance_cm

    def set_action_distance_threshold(self, distance_cm):
        """
        Set the distance threshold (in cm) for taking action on detected objects.
        
        Args:
            distance_cm (float): Distance threshold in centimeters
            
        Returns:
            float: The updated distance threshold
        """
        if distance_cm > 0:
            self.distance_threshold_cm = distance_cm
            logger.info(f"Action distance threshold set to {distance_cm} cm")
        else:
            logger.warning(f"Invalid distance threshold: {distance_cm}. Must be greater than 0")
        
        return self.distance_threshold_cm