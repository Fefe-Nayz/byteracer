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