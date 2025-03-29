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
    Detects camera issues and handles restart requests.
    """
    def __init__(self, vflip=False, hflip=False, local=False, web=True):
        self.vflip = vflip
        self.hflip = hflip
        self.local = local
        self.web = web
        self.state = CameraState.INACTIVE
        self.last_error = None
        self.last_start_time = 0
        self.last_health_check = 0
        self.health_check_interval = 5  # seconds
        self.max_restart_attempts = 3
        self.restart_attempts = 0
        self.restart_cooldown = 10  # seconds
        self.status_callback = None
        
        # Access to shared data
        self._lock = threading.Lock()
        self._health_check_task = None
        self._running = True
        
        logger.info("Camera Manager initialized")
    
    async def start(self, status_callback=None):
        """
        Start the camera and monitoring.
        
        Args:
            status_callback (callable): Optional callback for status updates
        """
        self.status_callback = status_callback
        
        # Start the camera
        success = await self._start_camera()
        
        # Begin health monitoring if camera started successfully
        if success:
            self._health_check_task = asyncio.create_task(self._monitor_camera_health())
            logger.info("Camera health monitoring started")
        
        return success
    
    async def stop(self):
        """Stop the camera and monitoring"""
        self._running = False
        
        # Cancel the health check task
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
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
                # Start the camera with vilib
                Vilib.camera_start(vflip=self.vflip, hflip=self.hflip)
                Vilib.display(local=self.local, web=self.web)
                
                # Wait a moment for camera to initialize
                await asyncio.sleep(1)
                
                self.state = CameraState.RUNNING
                self.restart_attempts = 0
                logger.info("Camera started successfully")
                
                # Notify via callback if one is registered
                if self.status_callback:
                    await self.status_callback({
                        "state": self.state.name,
                        "message": "Camera started successfully"
                    })
                
                return True
                
            except Exception as e:
                self.state = CameraState.ERROR
                self.last_error = str(e)
                logger.error(f"Failed to start camera: {e}")
                
                # Notify via callback if one is registered
                if self.status_callback:
                    await self.status_callback({
                        "state": self.state.name,
                        "error": self.last_error,
                        "message": "Failed to start camera"
                    })
                
                return False
    
    def _close_camera(self):
        """Close the camera safely"""
        try:
            Vilib.camera_close()
            logger.info("Camera closed successfully")
            return True
        except Exception as e:
            logger.error(f"Error closing camera: {e}")
            return False
    
    async def _monitor_camera_health(self):
        """Monitor camera health periodically"""
        logger.info("Starting camera health monitoring")
        
        while self._running:
            try:
                now = time.time()
                
                # Only check health at specified intervals
                if now - self.last_health_check >= self.health_check_interval:
                    self.last_health_check = now
                    
                    with self._lock:
                        # Only check if camera should be running
                        if self.state == CameraState.RUNNING:
                            # Check if camera is still responsive
                            # This depends on how vilib provides camera status
                            # For now, we'll use a simple approach
                            is_healthy = self._check_camera_health()
                            
                            if not is_healthy:
                                logger.warning("Camera health check failed")
                                await self._handle_camera_failure("Health check failed")
                
                # Sleep a bit to avoid tight loop
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                logger.info("Camera health monitoring cancelled")
                break
            except Exception as e:
                logger.error(f"Error in camera health monitoring: {e}")
                await asyncio.sleep(2)  # Longer sleep on error
    
    def _check_camera_health(self):
        """
        Check if the camera is responsive and working properly.
        
        Returns:
            bool: True if camera is healthy, False otherwise
        """
        try:
            # This is a placeholder - replace with actual health check
            # For example, you might check if recent frames were received
            # or if vilib has some internal status
            
            # For now, assume the camera is healthy if we can access it
            # You would need to adapt this to vilib's actual API
            return True
        except Exception as e:
            logger.error(f"Camera health check error: {e}")
            return False
    
    async def _handle_camera_failure(self, reason):
        """Handle camera failure by attempting restart"""
        with self._lock:
            if self.state == CameraState.RESTARTING:
                # Already restarting, don't overlap
                return
            
            self.state = CameraState.ERROR
            self.last_error = reason
            
            # Notify via callback
            if self.status_callback:
                await self.status_callback({
                    "state": self.state.name,
                    "error": self.last_error,
                    "message": "Camera failure detected"
                })
            
            # Check if we can attempt restart
            now = time.time()
            if self.restart_attempts < self.max_restart_attempts and \
               now - self.last_start_time > self.restart_cooldown:
                
                logger.info(f"Attempting camera restart ({self.restart_attempts + 1}/{self.max_restart_attempts})")
                self.state = CameraState.RESTARTING
                
                # Notify via callback
                if self.status_callback:
                    await self.status_callback({
                        "state": self.state.name,
                        "message": f"Restarting camera (attempt {self.restart_attempts + 1}/{self.max_restart_attempts})"
                    })
                
                # Close the camera
                self._close_camera()
                await asyncio.sleep(2)  # Give it time to fully close
                
                # Attempt restart
                self.restart_attempts += 1
                success = await self._start_camera()
                
                if not success:
                    logger.warning(f"Camera restart failed (attempt {self.restart_attempts}/{self.max_restart_attempts})")
            
            elif self.restart_attempts >= self.max_restart_attempts:
                logger.error("Maximum camera restart attempts reached")
                
                # Notify via callback
                if self.status_callback:
                    await self.status_callback({
                        "state": self.state.name,
                        "error": "Maximum restart attempts reached",
                        "message": "Unable to recover camera"
                    })
    
    async def restart(self):
        """
        Manually restart the camera.
        
        Returns:
            bool: True if restart was successful, False otherwise
        """
        with self._lock:
            logger.info("Manual camera restart requested")
            
            # Reset restart attempts for manual restart
            self.restart_attempts = 0
            self.state = CameraState.RESTARTING
            
            # Notify via callback
            if self.status_callback:
                await self.status_callback({
                    "state": self.state.name,
                    "message": "Manual camera restart initiated"
                })
            
            # Close the camera
            self._close_camera()
            await asyncio.sleep(2)  # Give it time to fully close
            
            # Start the camera again
            return await self._start_camera()
    
    def get_status(self):
        """Get the current camera status"""
        with self._lock:
            status = {
                "state": self.state.name,
                "error": self.last_error,
                "restart_attempts": self.restart_attempts,
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