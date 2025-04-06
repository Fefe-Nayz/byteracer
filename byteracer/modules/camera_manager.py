import asyncio
import time
import logging
import threading
from enum import Enum, auto
from vilib import Vilib

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
    def __init__(self, vflip=False, hflip=False, local=False, web=True):
        self.vflip = vflip
        self.hflip = hflip
        self.local = local
        self.web = web
        self.state = CameraState.INACTIVE
        self.last_error = None
        self.last_start_time = 0
        self.status_callback = None
        
        # Access to shared data
        self._lock = threading.Lock()
        
        logger.info("Camera Manager initialized")
    
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
                # Start the camera with vilib
                Vilib.camera_start(vflip=self.vflip, hflip=self.hflip)
                Vilib.display(local=self.local, web=self.web)
                
                # Wait a moment for camera to initialize
                await asyncio.sleep(1)
                
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
        Simplified restart method: close camera, wait 5 seconds, reopen camera.
        
        Returns:
            bool: True if restart was successful, False otherwise
        """
        logger.info("Simple camera restart requested")
        
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
        
        # Wait 5 seconds
        logger.info("Waiting 5 seconds before reopening camera...")
        await asyncio.sleep(5)
        
        # Start the camera again
        logger.info("Reopening camera...")
        return await self._start_camera()
    
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
                "web": self.web
            }
        }
        return status
    
    def update_settings(self, vflip=None, hflip=None, local=None, web=None):
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
        
        return restart_needed