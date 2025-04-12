import asyncio
import time
import logging
import threading
import importlib
import numpy as np
from enum import Enum, auto
from vilib import Vilib
from picamera2 import Picamera2

logger = logging.getLogger(__name__)

class CameraState(Enum):
    """Enum representing different camera states"""
    INACTIVE = auto()
    STARTING = auto()
    RUNNING = auto()
    ERROR = auto()
    RESTARTING = auto()
    FROZEN = auto()  # New state for frozen camera

class CameraManager:
    """
    Manages the camera feed and monitoring.
    Handles restart requests initiated by client.
    """
    def __init__(self, vflip=False, hflip=False, local=False, web=True, camera_size=(1920, 1080)):
        self.vflip = vflip
        self.hflip = hflip
        self.local = local
        self.web = web
        self.camera_size = camera_size
        self.state = CameraState.INACTIVE
        self.last_error = None
        self.last_start_time = 0
        self.status_callback = None
        
        # Access to shared data
        self._lock = threading.Lock()
        
        # Frame monitoring for freeze detection
        self._previous_frame = None
        self._last_frame_update_time = 0
        self._freeze_check_interval = 5  # Check every 5 seconds
        self._freeze_monitor_task = None
        self._is_frozen = False

        self.current_colors = None
        
        logger.info(f"Camera Manager initialized with resolution {self.camera_size}")
    
    async def start(self, status_callback=None):
        """
        Start the camera.
        
        Args:
            status_callback (callable): Optional callback for status updates
        """
        self.status_callback = status_callback
        
        # Start the camera
        success = await self._start_camera()
        
        # Start freeze monitoring if camera started successfully
        if success:
            self._freeze_monitor_task = asyncio.create_task(self._monitor_camera_freeze())
            logger.info("Camera freeze monitoring started")
        
        return success
    
    async def stop(self):
        """Stop the camera"""
        # Stop freeze monitoring
        if self._freeze_monitor_task:
            self._freeze_monitor_task.cancel()
            try:
                await self._freeze_monitor_task
            except asyncio.CancelledError:
                pass
            
        # Close the camera
        with self._lock:
            if self.state != CameraState.INACTIVE:
                self._close_camera()
                self.state = CameraState.INACTIVE
        
        logger.info("Camera stopped")
    
    async def _start_camera(self):
        """Start the camera and set initial state"""
        with self._lock:
            if self.state in [CameraState.RUNNING, CameraState.STARTING]:
                logger.info("Camera already running or starting")
                return True
            
            self.state = CameraState.STARTING
            self.last_start_time = time.time()
            
            try:
                # Ensure camera_size is a tuple before passing to camera_start
                camera_size = tuple(self.camera_size) if isinstance(self.camera_size, list) else self.camera_size
                
                # Start the camera with vilib, using the specified resolution
                logger.info(f"Starting camera with resolution {camera_size}")
                Vilib.camera_start(vflip=self.vflip, hflip=self.hflip, size=camera_size)
                Vilib.display(local=self.local, web=self.web)
                
                # Wait a moment for camera to initialize
                await asyncio.sleep(2)
                
                # Reset freeze detection state
                self._previous_frame = None
                self._last_frame_update_time = time.time()
                self._is_frozen = False
                
                self.state = CameraState.RUNNING
                logger.info("Camera started successfully")
                
                # Notify via callback if one is registered
                if self.status_callback:
                    try:
                        await self.status_callback({
                            "state": self.state.name,
                            "message": "Camera started successfully"
                        })
                    except Exception as e:
                        logger.error(f"Error in status callback: {e}")
                
                return True
                
            except Exception as e:
                self.state = CameraState.ERROR
                self.last_error = str(e)
                logger.error(f"Failed to start camera: {e}")
                
                # Notify via callback if one is registered
                if self.status_callback:
                    try:
                        await self.status_callback({
                            "state": self.state.name,
                            "error": self.last_error,
                            "message": "Failed to start camera"
                        })
                    except Exception as e:
                        logger.error(f"Error in status callback: {e}")
                
                return False
    
    def _close_camera(self):
        """Close the camera safely using vilib"""
        try:
            Vilib.camera_close()
            logger.info("Camera closed via vilib")
            return True
        except Exception as e:
            logger.error(f"Error closing camera via vilib: {e}")
            return False
    
    async def _monitor_camera_freeze(self):
        """Monitor camera feed for freezes by comparing frames periodically"""
        logger.info("Starting camera freeze monitoring")
        try:
            while True:
                # Only check for freezes when camera is running
                if self.state == CameraState.RUNNING:
                    try:
                        # Check if we have a new frame from the camera
                        current_frame = self._get_current_frame()
                        
                        # Only proceed if we have a frame to check
                        if current_frame is not None:
                            current_time = time.time()
                            
                            # If this is the first frame, or it's been 5+ seconds since last check
                            if self._previous_frame is None or (current_time - self._last_frame_update_time) >= self._freeze_check_interval:
                                # Compare current frame with previous frame
                                if self._previous_frame is not None:
                                    frames_different = self._compare_frames(self._previous_frame, current_frame)
                                    
                                    # Detected a change in frozen state
                                    if not frames_different and not self._is_frozen:
                                        # Camera just froze
                                        logger.warning("Camera freeze detected - no frame changes")
                                        self._is_frozen = True
                                        self.state = CameraState.FROZEN
                                        
                                        # Notify via callback
                                        if self.status_callback:
                                            try:
                                                await self.status_callback({
                                                    "state": self.state.name,
                                                    "message": "Camera feed frozen",
                                                    "error": "No frame changes detected"
                                                })
                                            except Exception as e:
                                                logger.error(f"Error in status callback: {e}")
                                                
                                    elif frames_different and self._is_frozen:
                                        # Camera recovered from freeze
                                        logger.info("Camera recovered from freeze - frame changes detected")
                                        self._is_frozen = False
                                        self.state = CameraState.RUNNING
                                        
                                        # Notify via callback
                                        if self.status_callback:
                                            try:
                                                await self.status_callback({
                                                    "state": self.state.name,
                                                    "message": "Camera feed recovered from freeze"
                                                })
                                            except Exception as e:
                                                logger.error(f"Error in status callback: {e}")
                                
                                # Save current frame for next comparison
                                self._previous_frame = current_frame
                                self._last_frame_update_time = current_time
                    except Exception as e:
                        logger.error(f"Error in freeze detection: {e}")
                
                # Wait before next check (short interval to not miss the 5 second window)
                await asyncio.sleep(1)
                
        except asyncio.CancelledError:
            logger.info("Camera freeze monitoring cancelled")
        except Exception as e:
            logger.error(f"Unexpected error in freeze monitoring: {e}")
    
    def _get_current_frame(self):
        """Safely get the current frame from Vilib"""
        try:
            # Vilib.img contains the current frame
            if hasattr(Vilib, 'img') and Vilib.img is not None:
                # Make a copy to avoid any potential race conditions
                return np.array(Vilib.img).copy()
            return None
        except Exception as e:
            logger.error(f"Error getting current frame: {e}")
            return None
    
    def _compare_frames(self, frame1, frame2):
        """
        Compare two frames to detect if they're different
        
        Returns:
            bool: True if frames are different, False if identical
        """
        try:
            # Make sure frames have the same shape
            if frame1.shape != frame2.shape:
                # Different shapes means different frames
                return True
                
            # Check if frames are identical - np.array_equal is faster than pixel-by-pixel comparison
            # We could use a tolerance for minor differences, but for freeze detection 
            # we want to detect even small changes
            return not np.array_equal(frame1, frame2)
        except Exception as e:
            logger.error(f"Error comparing frames: {e}")
            # On error, assume frames are different to avoid false positives
            return True
    
    async def restart(self):
        """
        Completely reinitialize the camera by resetting the Vilib Picamera2 instance.
        This avoids the NoneType errors when restarting.
        
        Returns:
            bool: True if restart was successful, False otherwise
        """
        logger.info("Camera restart requested - using full reinit approach")
        
        # Update state
        self.state = CameraState.RESTARTING
        
        # Notify via callback (with error handling)
        if self.status_callback:
            try:
                await self.status_callback({
                    "state": self.state.name,
                    "message": "Camera restart initiated"
                })
            except Exception as e:
                logger.error(f"Error in status callback: {e}")
        
        # Close the camera
        self._close_camera()
        
        # Wait for resources to be released
        logger.info("Waiting for camera resources to be released...")
        await asyncio.sleep(5)
        
        # Reset freeze detection state
        self._previous_frame = None
        self._is_frozen = False
        
        # Completely reinitialize the Picamera2 instance in Vilib
        try:
            logger.info("Reinitializing Picamera2 instance...")
            # Reset the static Picamera2 instance in Vilib
            Vilib.picam2 = Picamera2()
            Vilib.camera_run = False  # Ensure the camera thread is stopped
            
            # Set the camera size before starting
            # Ensure camera_size is a tuple
            camera_size = tuple(self.camera_size) if isinstance(self.camera_size, list) else self.camera_size
            Vilib.camera_size = camera_size
            
            # Wait a bit more for the new instance to initialize
            await asyncio.sleep(1)
            
            # Start the camera again
            logger.info(f"Starting camera with new Picamera2 instance and resolution {camera_size}...")
            return await self._start_camera()
        except Exception as e:
            logger.error(f"Error reinitializing camera: {e}")
            self.state = CameraState.ERROR
            self.last_error = str(e)
            return False
    
    def get_status(self):
        """Get the current camera status"""
        status = {
            "state": self.state.name,
            "error": self.last_error,
            "last_start_time": self.last_start_time,
            "frozen": self._is_frozen,
            "settings": {
                "vflip": self.vflip,
                "hflip": self.hflip,
                "local": self.local,
                "web": self.web,
                "resolution": f"{self.camera_size[0]}x{self.camera_size[1]}"
            }
        }
        return status
    
    def update_settings(self, vflip=None, hflip=None, local=None, web=None, camera_size=None):
        """
        Update camera settings.
        
        Returns:
            bool: True if settings were changed and require restart
        """
        restart_needed = False
        
        with self._lock:
            if vflip is not None and vflip != self.vflip:
                self.vflip = vflip
                restart_needed = True
            
            if hflip is not None and hflip != self.hflip:
                self.hflip = hflip
                restart_needed = True
            
            if local is not None and local != self.local:
                self.local = local
                restart_needed = True
            
            if web is not None and web != self.web:
                self.web = web
                restart_needed = True
                
            if camera_size is not None and camera_size != self.camera_size:
                # Convert camera_size to tuple if it's a list
                if isinstance(camera_size, list):
                    camera_size = tuple(camera_size)
                self.camera_size = camera_size
                logger.info(f"Camera resolution changed to {self.camera_size}")
                restart_needed = True
        
        return restart_needed
    def switch_face_detect(self, enable):
        """
        Enable or disable face detection.

        Args:
            enable (bool): True to enable, False to disable
        """
        if enable:
            Vilib.face_detect_switch(True)
            logger.info("Face detection enabled")
        else:
            Vilib.face_detect_switch(False)
            logger.info("Face detection disabled")

    def color_detect(self, color):
        """
        Enable color detection. Accepts either a single color (string)
        or multiple colors (list of strings). Valid colors:
            'red', 'green', 'blue', 'yellow', 'orange', 'purple'.

        Args:
            color (str or list): e.g. "red" or ["red", "blue"]
        """
        valid_colors = ['red', 'green', 'blue', 'yellow', 'orange', 'purple']

        # 1) Normalize to list
        if isinstance(color, str):
            color = [color]

        # 2) Validate each color
        color_lower_list = []
        for c in color:
            c_lower = c.lower()
            if c_lower not in valid_colors:
                logger.warning(
                    f"Invalid color '{c}'. Valid options: {', '.join(valid_colors)}"
                )
                return
            color_lower_list.append(c_lower)

        # 3) Store them
        self.current_colors = color_lower_list

        # 4) Call Vilib
        Vilib.color_detect(self.current_colors)

        # 5) Log
        if len(self.current_colors) == 1:
            single_color = self.current_colors[0]
            logger.info(f"{single_color.capitalize()} color detection enabled")
        else:
            logger.info(
                "Multi‐color detection enabled: "
                + ", ".join(self.current_colors)
            )

    def switch_color_detect(self, enable):
        """
        Enable or disable color detection.

        Args:
            enable (bool): True to enable, False to disable
        """
        if not enable:
            # Disable color detection
            Vilib.close_color_detection()
            self.current_colors = None
            logger.info("Color detection disabled")
        else:
            logger.info(
                "To enable color detection, call color_detect(...) "
                "with a valid color or list of colors."
            )

    def detect_obj_parameter(self, obj_type='human'):
        """
        Get the detected object parameters.

        Args:
            obj_type (str): Type of object to detect ('human', 'color', etc.)

        Returns:
            dict: Detected object parameters (coordinates, etc.).
                  If obj_type='color' and multiple colors are being tracked,
                  returns a list of bounding boxes—one per color.
        """
        if not hasattr(Vilib, 'detect_obj_parameter'):
            return {f'{obj_type}_detected': False}

        # The result that we'll return
        result = {}

        # 1) Face detection
        if obj_type == 'human':
            # Check if any face was detected
            if Vilib.detect_obj_parameter.get('human_n', 0) != 0:
                result['human_detected'] = True
                result['human_x'] = Vilib.detect_obj_parameter.get('human_x', 0)
                result['human_y'] = Vilib.detect_obj_parameter.get('human_y', 0)
                result['human_n'] = Vilib.detect_obj_parameter.get('human_n', 0)
                # width & height if present
                if 'human_w' in Vilib.detect_obj_parameter:
                    result['human_w'] = Vilib.detect_obj_parameter['human_w']
                if 'human_h' in Vilib.detect_obj_parameter:
                    result['human_h'] = Vilib.detect_obj_parameter['human_h']
            else:
                result['human_detected'] = False

        # 2) Color detection (updated for multi-color)
        elif obj_type == 'color':
            # We'll return an array of color objects, plus a flag for whether any color was found
            colors_detected_list = []
            any_color_found = False

            if self.current_colors:
                for color_name in self.current_colors:
                    # Build the dynamic keys (e.g. "red_n", "red_x")
                    n_key = f'{color_name}_n'
                    x_key = f'{color_name}_x'
                    y_key = f'{color_name}_y'
                    w_key = f'{color_name}_w'
                    h_key = f'{color_name}_h'

                    # Retrieve the number of detected contours
                    c_n = Vilib.detect_obj_parameter.get(n_key, 0)
                    if c_n > 0:
                        any_color_found = True
                        # Collect bounding-box data
                        color_info = {
                            'color_name': color_name,
                            'color_n': c_n,
                            'color_x': Vilib.detect_obj_parameter.get(x_key, 0),
                            'color_y': Vilib.detect_obj_parameter.get(y_key, 0),
                            'color_w': Vilib.detect_obj_parameter.get(w_key, 0),
                            'color_h': Vilib.detect_obj_parameter.get(h_key, 0),
                        }
                        colors_detected_list.append(color_info)
                    else:
                        # Even if a color isn't currently found, we can add a record for it,
                        # or skip it. Here, let's skip to keep the array only for found colors.
                        pass
            else:
                # No colors are enabled
                any_color_found = False

            # Summarize the result
            result['colors_detected'] = colors_detected_list
            result['any_color_found'] = any_color_found

        # 3) Else: some other object type or nothing found
        else:
            result[f'{obj_type}_detected'] = False

        return result