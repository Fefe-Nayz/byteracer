import asyncio
import time
import logging
import threading
import importlib
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
        
        return success
    
    async def stop(self):
        """Stop the camera"""
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
                # Start the camera with vilib, using the specified resolution
                logger.info(f"Starting camera with resolution {self.camera_size}")
                Vilib.camera_start(vflip=self.vflip, hflip=self.hflip, size=self.camera_size)
                Vilib.display(local=self.local, web=self.web)
                
                # Wait a moment for camera to initialize
                await asyncio.sleep(2)
                
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
        
        # Completely reinitialize the Picamera2 instance in Vilib
        try:
            logger.info("Reinitializing Picamera2 instance...")
            # Reset the static Picamera2 instance in Vilib
            Vilib.picam2 = Picamera2()
            Vilib.camera_run = False  # Ensure the camera thread is stopped
            
            # Set the camera size before starting
            Vilib.camera_size = self.camera_size
            
            # Wait a bit more for the new instance to initialize
            await asyncio.sleep(1)
            
            # Start the camera again
            logger.info(f"Starting camera with new Picamera2 instance and resolution {self.camera_size}...")
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
                self.camera_size = camera_size
                logger.info(f"Camera resolution changed to {self.camera_size}")
                restart_needed = True
        
        return restart_needed