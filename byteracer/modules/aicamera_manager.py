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
    def __init__(self, px, sensor_manager, camera_manager, tts_manager, config_manager):
        # Robot control/hardware
        self.px = px
        self.sensor_manager = sensor_manager
        self.camera_manager = camera_manager
        self.tts_manager = tts_manager
        self.config_manager = config_manager

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
        
        # YOLO object detection
        self.yolo_model = None
        self.yolo_detection_thread = None
        self.yolo_detection_active = False
        self.yolo_min_confidence = 0.5
        self.yolo_results = []
        self.yolo_object_count = 0
        # Extract camera width and height from config
        camera_size = self.config_manager.get("camera.camera_size", [640, 480])
        self.camera_width = camera_size[0]  # First element is width
        self.camera_height = camera_size[1]  # Second element is height

        # Traffic sign state variables
        self.traffic_light_state = None  # Can be "red", "green", "yellow" or None
        self.traffic_light_detected = False
        self.waiting_for_green = False  # Flag to track if we're waiting for green after seeing red
        self.traffic_light_distance_threshold = 0.02  # Object must be at least this fraction of the frame size
        
        # Stop sign state variables
        self.stop_sign_detected = False
        self.stop_sign_timer = None  # For tracking the 2-second stop duration
        self.waiting_at_stop_sign = False
        
        # Right turn sign state variables 
        self.right_turn_sign_detected = False
        self.right_turn_timer = None  # For tracking the 2-second delay before turning
        self.executing_right_turn = False
        self.right_turn_time = 2.0  # Duration of a right turn in seconds, can be adjusted for calibration
        
        # Continuous turning state
        self.continuous_turning = False  # Flag to track if continuous turning is active
        
        # Auto-load YOLO model if available in modules directory
        self.model_path = os.path.join(os.path.dirname(__file__), 'model.pt')
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
    #     Adjust as needed to act on 'stop', 'left', 'right', etc.
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
            return
        
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

        # Stop any continuous turn if it's active
        if hasattr(self, 'continuous_turning') and self.continuous_turning:
            self.stop_continuous_turn()

        # Disable drawing overlays
        try:
            self.camera_manager.disable_vilib_drawing()
        except Exception as e:
            logger.error(f"Error disabling vilib drawing: {e}")

        self.px.forward(0)  # Stop the robot
    
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
        
        frame_rate_buffer = []
        fps_avg_len = 30
        avg_frame_rate = 0
        
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
                
                # Run inference on frame
                results = self.yolo_model(frame, verbose=False)
                
                # Extract results
                detections = results[0].boxes
                self.yolo_results = results  # Store for external access
                
                # Reset object count
                self.yolo_object_count = 0
                
                # Display detections on vilib camera feed for web/local display
                self.camera_manager.display_yolo_detections_on_vilib(detections, self.yolo_labels, self.yolo_min_confidence)
                
                # Find objects to track
                best_object = None
                best_confidence = 0
                traffic_light_object = None
                stop_sign_object = None
                right_turn_object = None
                
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
                    
                    # Count objects above confidence threshold
                    if conf > self.yolo_min_confidence:
                        self.yolo_object_count += 1
                        
                        # Create object info dictionary
                        object_info = {
                            'class': classname,
                            'confidence': conf,
                            'x': (xmin + xmax) // 2,
                            'y': (ymin + ymax) // 2,
                            'width': xmax - xmin,
                            'height': ymax - ymin
                        }
                        
                        # Check for different types of objects we're interested in
                        if classname in ["red", "green", "yellow"]:
                            # For traffic lights, we always keep the most confident one
                            if traffic_light_object is None or conf > traffic_light_object['confidence']:
                                traffic_light_object = object_info
                                logger.info(f"Detected traffic light: {classname} with confidence {conf:.2f}")
                        elif classname == "stop":
                            # For stop signs, keep the most confident one
                            if stop_sign_object is None or conf > stop_sign_object['confidence']:
                                stop_sign_object = object_info
                                logger.info(f"Detected stop sign with confidence {conf:.2f}")
                        elif classname == "right":
                            # For right turn signs, keep the most confident one
                            if right_turn_object is None or conf > right_turn_object['confidence']:
                                right_turn_object = object_info
                                logger.info(f"Detected right turn sign with confidence {conf:.2f}")
                        
                        # For general object tracking, track the highest confidence object
                        if conf > best_confidence:
                            best_confidence = conf
                            best_object = object_info
                
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
                    for i in range(len(detections)):
                        conf = detections[i].conf.item()
                        if conf > self.yolo_min_confidence:
                            classidx = int(detections[i].cls.item())
                            classname = self.yolo_labels[classidx]
                            objects_info.append(f"{classname} ({conf:.2f})")
                    
                    logger.info(f"Detected objects: {', '.join(objects_info)}")
                
                logger.info(f"YOLO detection: {self.yolo_object_count} objects, FPS: {avg_frame_rate:.1f}")
                
            except Exception as e:
                logger.error(f"Error in YOLO detection loop: {e}")
                await asyncio.sleep(0.1)
        
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
        
        Args:
            object_info (dict): Object detection info including x, y coordinates
        """
        x, y = object_info['x'], object_info['y']
        
        # Calculate offset from center of frame
        x_offset_ratio = (x / self.camera_width) - 0.5
        target_x_angle = x_offset_ratio * 180  # Scale to ±90°
        
        dx = target_x_angle - self.x_angle
        self.x_angle += 0.2 * dx  # Smooth movement factor
        self.x_angle = self.clamp_number(self.x_angle, self.PAN_MIN_ANGLE, self.PAN_MAX_ANGLE)
        self.px.set_cam_pan_angle(int(self.x_angle))
        
        y_offset_ratio = 0.5 - (y / self.camera_height)
        target_y_angle = y_offset_ratio * 130  # Scale to tilt range
        
        dy = target_y_angle - self.y_angle
        self.y_angle += 0.2 * dy  # Smooth movement factor
        self.y_angle = self.clamp_number(self.y_angle, self.TILT_MIN_ANGLE, self.TILT_MAX_ANGLE)
        self.px.set_cam_tilt_angle(int(self.y_angle))
        
        logger.debug(
            f"Tracking {object_info['class']} at ({x},{y}), "
            f"confidence: {object_info['confidence']:.2f}, "
            f"camera pan={self.x_angle:.1f}, tilt={self.y_angle:.1f}"
        )
    
    async def _handle_traffic_light(self, class_name, object_info):
        """
        Handle traffic light detection and corresponding robot behavior.
        
        Args:
            class_name (str): The detected class name ("red", "green", or "yellow")
            object_info (dict): Object information with coordinates, size, etc.
        """
        # If it's not a traffic light, reset if we were previously tracking one
        if class_name not in ["red", "green", "yellow"]:
            if self.traffic_light_detected:
                logger.info("Lost track of traffic light")
                self.traffic_light_detected = False
                self.traffic_light_state = None
            return
        
        # Get object dimensions
        width = object_info['width']
        height = object_info['height']
        
        # Calculate object size relative to frame
        relative_size = (width * height) / (self.camera_width * self.camera_height)
        is_close_enough = relative_size > self.traffic_light_distance_threshold
        
        # Update traffic light state
        prev_state = self.traffic_light_state
        self.traffic_light_state = class_name
        self.traffic_light_detected = True
        
        # Log detection
        if is_close_enough:
            logger.info(f"Traffic light {class_name} detected and is close enough (size: {relative_size:.2f})")
        else:
            logger.info(f"Traffic light {class_name} detected but not close enough yet (size: {relative_size:.2f})")
        
        # Handle traffic light behavior
        if is_close_enough:
            # Handle red and yellow lights (both require stopping)
            if class_name in ["red", "yellow"] and (prev_state not in ["red", "yellow"] or not self.waiting_for_green):
                # Red or Yellow light - stop and announce
                self.px.forward(0)
                self.waiting_for_green = True
                
                # Announce if TTS manager is available
                if self.tts_manager:
                    await self.tts_manager.say(f"{class_name.capitalize()} light detected", priority=1)
                
                logger.info(f"{class_name.upper()} LIGHT - Stopping robot")
                
            elif class_name == "green":
                if self.waiting_for_green:
                    # We were waiting for green after seeing red/yellow, now proceed
                    self.px.forward(1)  # 10% speed
                    self.waiting_for_green = False
                    
                    # Announce if TTS manager is available
                    if self.tts_manager:
                        await self.tts_manager.say("Green light detected", priority=1)
                    
                    logger.info("GREEN LIGHT after stopping - Proceeding at 10% speed")
                elif prev_state != "green":
                    # Green light from no previous light detected
                    self.px.forward(1)  # 10% speed
                    
                    # Announce if TTS manager is available
                    if self.tts_manager:
                        await self.tts_manager.say("Green light detected", priority=1)

                    logger.info("GREEN LIGHT - Proceeding at 10% speed")
        elif not self.waiting_for_green:
            # If not close enough and not waiting for green after red/yellow, move forward
            self.px.forward(1)  # 10% speed
            logger.info("GREEN LIGHT - Proceeding at 10% speed")
            
    async def _handle_stop_sign(self, object_info):
        """
        Handle stop sign detection and corresponding robot behavior.
        
        Args:
            object_info (dict): Object information with coordinates, size, etc.
        """
        # Get object dimensions
        width = object_info['width']
        height = object_info['height']
        
        # Calculate object size relative to frame
        relative_size = (width * height) / (self.camera_width * self.camera_height)
        is_close_enough = relative_size > self.traffic_light_distance_threshold
        
        # Update stop sign state
        self.stop_sign_detected = True
        
        # Log detection
        if is_close_enough:
            logger.info(f"Stop sign detected and is close enough (size: {relative_size:.2f})")
        else:
            logger.info(f"Stop sign detected but not close enough yet (size: {relative_size:.2f})")
        
        # Handle stop sign behavior
        if is_close_enough and not self.waiting_at_stop_sign:
            # Stop sign is close enough - stop for 2 seconds
            self.px.forward(0)
            self.waiting_at_stop_sign = True
            
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
                self.px.forward(1)  # 10% speed
                self.waiting_at_stop_sign = False
                
                # Announce if TTS manager is available
                if self.tts_manager:
                    await self.tts_manager.say("Proceeding after stop", priority=1)
                
                logger.info("STOP SIGN - Waited 2 seconds, now proceeding at 10% speed")
        elif not self.waiting_at_stop_sign:
            # Not close enough yet, continue moving forward
            self.px.forward(1)  # 10% speed
            logger.info("Stop sign detected but not close enough, proceeding at 10% speed")
    
    async def _handle_right_turn_sign(self, object_info):
        """
        Handle right turn sign detection and corresponding robot behavior.
        
        Args:
            object_info (dict): Object information with coordinates, size, etc.
        """
        # Get object dimensions
        width = object_info['width']
        height = object_info['height']
        
        # Calculate object size relative to frame
        relative_size = (width * height) / (self.camera_width * self.camera_height)
        is_close_enough = relative_size > self.traffic_light_distance_threshold
        
        # Update right turn sign state
        self.right_turn_sign_detected = True
        
        # Log detection
        if is_close_enough:
            logger.info(f"Right turn sign detected and is close enough (size: {relative_size:.2f})")
        else:
            logger.info(f"Right turn sign detected but not close enough yet (size: {relative_size:.2f})")
        
        # Handle right turn sign behavior
        if is_close_enough and not self.executing_right_turn and self.right_turn_timer is None:
            # Right turn sign is close enough - prepare to turn in 2 seconds
            logger.info("RIGHT TURN SIGN - Will turn right in 2 seconds")
            
            # Announce if TTS manager is available
            if self.tts_manager:
                await self.tts_manager.say("Right turn ahead", priority=1)
            
            # Start timer to execute turn after 2 seconds
            self.right_turn_timer = time.time()
            
        elif self.right_turn_timer is not None and not self.executing_right_turn:
            # Check if it's time to turn (2 seconds after detection)
            if time.time() - self.right_turn_timer >= 2.0:                # Execute right turn
                self.executing_right_turn = True
                
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
                self.px.set_motor_speed(1, 10)  # Return to normal forward speed (10%)
                self.px.set_motor_speed(2, -10) # Return to normal forward speed (10%)
                
                # Reset turn state
                self.right_turn_timer = None
                self.executing_right_turn = False
                self.right_turn_sign_detected = False

                # Move forward slowly after the turn
                self.px.forward(1)  # 10% speed
                
                logger.info("RIGHT TURN SIGN - Turn completed, continuing forward")
        
        elif not is_close_enough and not self.executing_right_turn:
            # Not close enough yet, continue moving forward
            self.px.forward(1)  # 10% speed
            logger.info("Right turn sign detected but not close enough, proceeding at 10% speed")
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
            
            logger.info("Calibration turn completed")
            
            # Announce completion if TTS is available
            if self.tts_manager:
                await self.tts_manager.say("Turn calibration completed", priority=1)
            
            logger.info("Check if the robot turned approximately 90 degrees.")
            logger.info("If not, adjust the turn parameters in _handle_right_turn_sign method.")
            logger.info("----- END OF CALIBRATION TEST -----")
            
        except Exception as e:
            logger.error(f"Error in right turn test: {e}")
            # Stop the robot if there was an error
            self.px.forward(0)
            self.px.set_dir_servo_angle(0)


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