import time
import logging
import threading
import math
import os
import sys
import numpy as np
import cv2
from ultralytics import YOLO

logger = logging.getLogger(__name__)

class AICameraCameraManager:
    """
    Manages higher-level AI camera capabilities, specifically:
      1) Traffic light color detection and speed control (red, green, orange).
      2) Face detection + following (forward/back & turn).
      3) Pose detection.
      4) Traffic-sign detection.
      5) YOLO object detection using camera feed.
    """    
    def __init__(self, px, sensor_manager, camera_manager, tts_manager):
        # Robot control/hardware
        self.px = px
        self.sensor_manager = sensor_manager
        self.camera_manager = camera_manager
        self.tts_manager = tts_manager

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
        self.pose_detection_active = False        # Traffic-sign detection
        self.traffic_sign_detection_thread = None
        self.traffic_sign_detection_active = False
        
        # YOLO object detection
        self.yolo_model = None
        self.yolo_detection_thread = None
        self.yolo_detection_active = False
        self.yolo_min_confidence = 0.5
        self.yolo_results = []
        self.yolo_object_count = 0
        self.camera_width = 640
        self.camera_height = 480
        
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

        # Traffic light state
        self.traffic_light_state = None  # Can be "red", "green", or None
        self.traffic_light_detected = False
        self.waiting_for_green = False  # Flag to track if we're waiting for green after seeing red
        self.traffic_light_distance_threshold = 0.1  # Object must be at least this fraction of the frame size to be considered "close enough"
        
        # TTS Manager reference for announcements

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
            # Use provided path or auto-load default
            if not self.load_yolo_model(model_path):
                logger.error("Failed to load YOLO model. Cannot start detection.")
                return False
        
        logger.info("Starting YOLO object detection...")
        self.yolo_detection_active = True
        
        # Reset camera angles
        self.x_angle = 0
        self.y_angle = 0
        
        # Start the detection thread
        self.yolo_detection_thread = threading.Thread(
            target=self._yolo_detection_loop,
            daemon=True
        )
        self.yolo_detection_thread.start()
        return True
    
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
    
    def _yolo_detection_loop(self):
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
                    time.sleep(0.1)
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
                  # Find the most prominent object to track (highest confidence)
                best_object = None
                best_confidence = 0
                traffic_light_object = None
                
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
                        
                        # Check if this is a traffic light (red or green)
                        if classname in ["red", "green"]:
                            # For traffic lights, we always keep the most confident one
                            if traffic_light_object is None or conf > traffic_light_object['confidence']:
                                traffic_light_object = object_info
                                logger.info(f"Detected traffic light: {classname} with confidence {conf:.2f}")
                        
                        # For general object tracking, track the highest confidence object
                        if conf > best_confidence:
                            best_confidence = conf
                            best_object = object_info
                
                # Handle traffic light detection and behavior
                if traffic_light_object:
                    self._handle_traffic_light(traffic_light_object['class'], traffic_light_object)
                    # Traffic lights take priority for tracking
                    best_object = traffic_light_object
                elif not self.waiting_for_green:
                    # If no traffic light is detected and we're not waiting for a green light,
                    # move forward at default speed
                    self.px.forward(10)  # 10% speed
                
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
                
                # Sleep to avoid consuming too much CPU
                time.sleep(0.01)
                
            except Exception as e:
                logger.error(f"Error in YOLO detection loop: {e}")
                time.sleep(0.1)
        
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
    
    def get_yolo_results(self):
        """
        Get the latest YOLO detection results.
        
        Returns:
            list: YOLO detection results
        """
        return self.yolo_results
    
    def get_yolo_object_count(self):
        """
        Get the number of objects detected above the confidence threshold.
        
        Returns:
            int: Number of detected objects
        """
        return self.yolo_object_count
    
    def process_single_frame(self, frame=None):
        """
        Process a single frame with the YOLO model and return results.
        This method doesn't affect ongoing detection in the background thread.
        
        Args:
            frame (numpy.ndarray, optional): Frame to process. If None, get current camera frame.
        
        Returns:
            tuple: (processed_frame, num_objects, detections)
        """
        if self.yolo_model is None:
            logger.error("YOLO model not loaded. Call load_yolo_model() first.")
            return None, 0, []
        
        try:
            import cv2
        except ImportError:
            logger.error("cv2 not installed. Cannot process frame.")
            return None, 0, []
        
        # Get frame if not provided
        if frame is None:
            frame = self._get_camera_frame()
            if frame is None:
                return None, 0, []
        
        # Convert frame format if needed
        if len(frame.shape) == 2:  # If grayscale
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        
        # Make a copy to draw on
        output_frame = frame.copy()
        
        # Run inference
        results = self.yolo_model(frame, verbose=False)
        detections = results[0].boxes
        
        # Count objects above threshold
        object_count = 0
        
        # Process each detection
        for i in range(len(detections)):
            # Get bounding box coordinates
            xyxy_tensor = detections[i].xyxy.cpu()
            xyxy = xyxy_tensor.numpy().squeeze()
            xmin, ymin, xmax, ymax = xyxy.astype(int)
            
            # Get class info
            classidx = int(detections[i].cls.item())
            classname = self.yolo_labels[classidx]
            conf = detections[i].conf.item()
            
            # Draw if above threshold
            if conf > self.yolo_min_confidence:
                color = self.bbox_colors[classidx % 10]
                cv2.rectangle(output_frame, (xmin, ymin), (xmax, ymax), color, 2)
                
                # Add label
                label = f'{classname}: {int(conf*100)}%'
                labelSize, baseLine = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                label_ymin = max(ymin, labelSize[1] + 10)
                cv2.rectangle(output_frame, (xmin, label_ymin-labelSize[1]-10), 
                             (xmin+labelSize[0], label_ymin+baseLine-10), color, cv2.FILLED)
                cv2.putText(output_frame, label, (xmin, label_ymin-7), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
                
                object_count += 1
          # Add object count to image
        cv2.putText(output_frame, f'Objects: {object_count}', (10, 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        
        # Print detected objects
        if object_count > 0:
            objects_info = []
            for i in range(len(detections)):
                conf = detections[i].conf.item()
                if conf > self.yolo_min_confidence:
                    classidx = int(detections[i].cls.item())
                    classname = self.yolo_labels[classidx]
                    objects_info.append(f"{classname} ({conf:.2f})")
            
            print(f"Detected objects: {', '.join(objects_info)}")
        
        return output_frame, object_count, detections
    
    def run_object_detection_on_camera(self, duration=None, display=False):
        """
        Run object detection on the camera feed for the specified duration.
        This is a simple demonstration method that doesn't require setting up threads.
        
        Args:
            duration (float, optional): How many seconds to run detection. If None, runs until user interrupts.
            display (bool): Whether to display the results in a window (requires cv2 and running with display).
            
        Returns:
            dict: Summary of detection statistics
        """
        # Make sure the model is loaded
        if self.yolo_model is None:
            if not self.load_yolo_model():
                return {"error": "Failed to load model"}
        
        try:
            import cv2
            import numpy as np
        except ImportError:
            return {"error": "OpenCV not installed"}
            
        start_time = time.time()
        frame_count = 0
        detection_counts = {}
        
        try:
            # Set up display window if requested
            if display:
                cv2.namedWindow("Object Detection", cv2.WINDOW_NORMAL)
                
            while True:
                # Check if we've exceeded the specified duration
                if duration and (time.time() - start_time) > duration:
                    break
                    
                # Get frame from camera
                frame = self._get_camera_frame()
                if frame is None:
                    logger.warning("No frame available")
                    time.sleep(0.1)
                    continue
                
                # Process the frame with YOLO
                output_frame, obj_count, detections = self.process_single_frame(frame)
                frame_count += 1
                
                # Count objects by class
                for i in range(len(detections)):
                    conf = detections[i].conf.item()
                    if conf > self.yolo_min_confidence:
                        class_id = int(detections[i].cls.item())
                        class_name = self.yolo_labels[class_id]
                        
                        if class_name in detection_counts:
                            detection_counts[class_name] += 1
                        else:
                            detection_counts[class_name] = 1
                
                # Display the frame if requested
                if display and output_frame is not None:
                    cv2.imshow("Object Detection", output_frame)
                    
                    # Exit if 'q' is pressed
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                        
                # Short sleep to avoid consuming all CPU
                time.sleep(0.01)
                
        except KeyboardInterrupt:
            logger.info("Detection interrupted by user")
        except Exception as e:
            logger.error(f"Error in detection demo: {e}")
        finally:
            if display:
                cv2.destroyAllWindows()
                
        # Calculate statistics
        elapsed_time = time.time() - start_time
        fps = frame_count / elapsed_time if elapsed_time > 0 else 0
                
        # Return detection summary
        return {
            "elapsed_time": elapsed_time,
            "frames_processed": frame_count,
            "fps": fps,
            "detections": detection_counts
        }
    

    def _handle_traffic_light(self, class_name, object_info):
        """
        Handle traffic light detection and corresponding robot behavior.
        
        Args:
            class_name (str): The detected class name ("red" or "green")
            object_info (dict): Object information with coordinates, size, etc.
        """
        # If it's not a traffic light, reset if we were previously tracking one
        if class_name not in ["red", "green"]:
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
            # Only announce state changes to avoid repetition
            if class_name == "red" and (prev_state != "red" or not self.waiting_for_green):
                # Red light - stop and announce
                self.px.forward(0)
                self.waiting_for_green = True
                
                # Announce if TTS manager is available
                if self.tts_manager:
                    self.tts_manager.say("feu rouge détecté", priority=1)
                
                logger.info("RED LIGHT - Stopping robot")
                
            elif class_name == "green":
                if self.waiting_for_green:
                    # We were waiting for green after seeing red, now proceed
                    self.px.forward(10)  # 10% speed
                    self.waiting_for_green = False
                    
                    # Announce if TTS manager is available
                    if self.tts_manager:
                        self.tts_manager.say("feu vert détecté", priority=1)
                    
                    logger.info("GREEN LIGHT after RED - Proceeding at 10% speed")
                elif prev_state != "green":
                    # Green light from no previous light detected
                    self.px.forward(10)  # 10% speed
                    
                    # Announce if TTS manager is available
                    if self.tts_manager:
                        self.tts_manager.say("feu vert détecté", priority=1)

                    logger.info("GREEN LIGHT - Proceeding at 10% speed")
        elif not self.waiting_for_green:
            # If not close enough and not waiting for green after red, move forward
            self.px.forward(10)  # 10% speed
            logger.info("Traffic light detected but not close enough, proceeding at 10% speed")
