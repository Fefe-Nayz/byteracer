import asyncio
import time
import logging
import threading
import subprocess
import re
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
        self.restart_attempts = 0
        self.max_restart_attempts = 3
        self.restart_cooldown = 10  # seconds
        self.status_callback = None
        
        # Access to shared data
        self._lock = threading.Lock()
        self._running = True
        
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
        self._running = False
        
        # Close the camera
        with self._lock:
            if self.state != CameraState.INACTIVE:
                await self._close_camera_completely()
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
        """Close the camera safely using vilib"""
        try:
            Vilib.camera_close()
            logger.info("Camera closed via vilib")
            return True
        except Exception as e:
            logger.error(f"Error closing camera via vilib: {e}")
            return False
    
    async def _run_libcamera_hello(self, timeout=60):
        """
        Run libcamera-hello to check camera availability and wait for it to finish.
        
        Args:
            timeout (int): Maximum time to wait for camera to become available
        
        Returns:
            bool: True if camera became available, False if still unavailable after timeout
        """
        logger.info("Running libcamera-hello to test camera availability")
        
        process = await asyncio.create_subprocess_exec(
            "sudo", "libcamera-hello",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        
        start_time = time.time()
        camera_available = False
        output_lines = []
        
        while True:
            # Check if we've exceeded timeout
            if time.time() - start_time > timeout:
                logger.error(f"Timeout waiting for camera to become available")
                try:
                    process.terminate()
                except:
                    pass
                break
            
            # Read line from process output
            try:
                line = await asyncio.wait_for(process.stdout.readline(), 1.0)
                if not line:
                    break
                
                line_str = line.decode('utf-8', errors='replace').strip()
                output_lines.append(line_str)
                
                # Log output for debugging
                logger.debug(f"libcamera-hello output: {line_str}")
                
                # Check for successful initialization pattern
                # This indicates camera is not in use by another process
                if re.search(r'#\d+ \(\d+\.\d+ fps\)', line_str):
                    camera_available = True
                    logger.info("Camera appears to be available (seeing frame rates)")
                    try:
                        process.terminate()
                    except:
                        pass
                    break
                
                # Check for error pattern indicating camera is in use
                if "Camera pipeline handler in use by another process" in line_str or \
                   "failed to acquire camera" in line_str or \
                   "Camera.cpp:1008 Pipeline handler in use by another process" in line_str:
                    logger.warning("Camera still in use by another process")
                    # Don't break here, continue waiting until timeout
            
            except asyncio.TimeoutError:
                # This is just the read timeout, continue waiting
                await asyncio.sleep(0.1)
                continue
            except Exception as e:
                logger.error(f"Error reading libcamera-hello output: {e}")
                break
        
        # Ensure process is terminated
        if process.returncode is None:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), 5.0)
            except:
                pass
        
        if not camera_available:
            logger.error("Camera did not become available within timeout period")
            logger.debug("Full libcamera-hello output:")
            for line in output_lines:
                logger.debug(f"  {line}")
        
        return camera_available
    
    async def _close_camera_completely(self):
        """Close camera and ensure it's fully released using libcamera-hello"""
        # First close with vilib
        self._close_camera()
        
        # Then wait for camera to be fully released by checking with libcamera-hello
        camera_released = False
        max_attempts = 5
        attempt = 0
        
        while not camera_released and attempt < max_attempts:
            attempt += 1
            logger.info(f"Waiting for camera to be fully released (attempt {attempt}/{max_attempts})")
            
            # Sleep to give time for resources to be released
            await asyncio.sleep(2)
            
            # Check camera availability
            camera_released = await self._run_libcamera_hello()
            
            if camera_released:
                logger.info("Camera successfully released")
            else:
                logger.warning(f"Camera not fully released yet (attempt {attempt}/{max_attempts})")
        
        return camera_released
    
    async def restart(self):
        """
        Manually restart the camera with proper release and initialization checks.
        
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
            
            # Close the camera and ensure it's fully released
            logger.info("Closing camera and waiting for full release...")
            camera_released = await self._close_camera_completely()
            
            if not camera_released:
                self.state = CameraState.ERROR
                self.last_error = "Failed to fully release camera"
                logger.error("Failed to fully release camera for restart")
                
                # Notify via callback
                if self.status_callback:
                    await self.status_callback({
                        "state": self.state.name,
                        "error": self.last_error,
                        "message": "Camera restart failed - could not release camera"
                    })
                
                return False
            
            logger.info("Camera fully released, restarting...")
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