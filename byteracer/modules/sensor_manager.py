import asyncio
import time
import logging
from enum import Enum, auto
from typing import Callable, Dict, Any, Optional
import threading

logger = logging.getLogger(__name__)

class EmergencyState(Enum):
    """Enum representing different emergency states"""
    NONE = auto()
    COLLISION_FRONT = auto()
    COLLISION_REAR = auto()
    EDGE_DETECTED = auto()
    CLIENT_DISCONNECTED = auto()
    LOW_BATTERY = auto()
    MANUAL_STOP = auto()

class SensorManager:
    """
    Manages all sensors and detects emergency situations.
    Implements collision avoidance and edge detection.
    """
    def __init__(self, picarx_instance, emergency_callback=None):
        self.px = picarx_instance
        self.px.set_cliff_reference([200, 200, 200])
        self.emergency_callback = emergency_callback
        
        # Emergency states
        self.current_emergency = EmergencyState.NONE
        self.emergency_active = False
        self._last_emergency_time = 0
        self._emergency_cooldown = 2.0  # Seconds
        
        # Sensor readings
        self.ultrasonic_distance = float('inf')  # In cm
        self.line_sensors = [0, 0, 0]  # Left, center, right
        self.last_input_time = time.time()
        self.last_client_seen = time.time()
        self.battery_level = 100
        
        # Safety thresholds
        self.collision_threshold = 20  # cm
        self.edge_detection_threshold = 0.2  # Normalized line sensor reading
        self.client_timeout = 15  # seconds
        self.low_battery_threshold = 15  # percentage
        self.low_battery_last_warning = 0
        self.low_battery_warning_interval = 60  # seconds
        
        # Safety features
        self.collision_avoidance_enabled = True
        self.edge_detection_enabled = True
        self.auto_stop_enabled = True
        self.tracking_enabled = False
        self.circuit_mode_enabled = False
        
        # Tracking data
        self.current_speed = 0.0
        self.current_turn = 0.0
        self.previous_speed = 0.0
        self.accel_history = []
        self.max_accel_history = 10
        self.accel_update_time = time.time()
        
        # Tasks
        self._running = True
        self._sensors_task = None
        self._lock = threading.Lock()
        
        logger.info("Sensor Manager initialized")
    
    async def start(self):
        """Start the sensor monitoring tasks"""
        self._sensors_task = asyncio.create_task(self._monitor_sensors())
        logger.info("Sensor monitoring started")
    
    async def stop(self):
        """Stop the sensor monitoring tasks"""
        self._running = False
        if self._sensors_task:
            self._sensors_task.cancel()
            try:
                await self._sensors_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Sensor monitoring stopped")
    
    async def _monitor_sensors(self):
        """Main sensor monitoring loop"""
        logger.info("Starting sensor monitoring loop")
        while self._running:
            try:
                # Update sensor readings
                await self._update_sensor_readings()
                
                # Check for emergencies
                emergency = self._check_emergency_conditions()
                
                # Handle any detected emergency
                if emergency != EmergencyState.NONE:
                    await self._handle_emergency(emergency)
                elif self.emergency_active:
                    # Clear emergency if conditions are safe
                    await self._clear_emergency()
                
                # Short delay to avoid CPU overuse
                await asyncio.sleep(0.1)
                
            except asyncio.CancelledError:
                logger.info("Sensor monitoring loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in sensor monitoring loop: {e}")
                await asyncio.sleep(1)  # Avoid tight loop on error
    
    async def _update_sensor_readings(self):
        """Update all sensor readings"""
        try:
            # Get ultrasonic distance
            # Assuming px has get_distance() method
            dist = self.px.get_distance()
            if dist is not None and dist > 0:
                self.ultrasonic_distance = dist
            
            # Get line sensors
            # Assuming px has get_grayscale_data() method for the 3 line sensors
            line_data = self.px.get_grayscale_data()
            if line_data is not None and len(line_data) == 3:
                self.line_sensors = line_data
            
            # Update acceleration data
            now = time.time()
            dt = now - self.accel_update_time
            if dt > 0:
                accel = (self.current_speed - self.previous_speed) / dt
                self.accel_history.append(accel)
                if len(self.accel_history) > self.max_accel_history:
                    self.accel_history.pop(0)
                self.previous_speed = self.current_speed
                self.accel_update_time = now
            
        except Exception as e:
            logger.error(f"Error updating sensor readings: {e}")
    
    def _check_emergency_conditions(self):
        """Check all emergency conditions and return the highest priority one"""
        now = time.time()
        
        # Only check for new emergencies after cooldown period
        if now - self._last_emergency_time < self._emergency_cooldown:
            return EmergencyState.NONE
        
        # Check for obstacles if collision avoidance is enabled
        if self.collision_avoidance_enabled and self.ultrasonic_distance < self.collision_threshold:
            # If moving forward and obstacle in front
            if self.current_speed > 0:
                return EmergencyState.COLLISION_FRONT
            # If moving backward and obstacle behind
            elif self.current_speed < 0:
                return EmergencyState.COLLISION_REAR
        
        # Check for edges if edge detection is enabled
        if self.edge_detection_enabled:
            # Simple edge detection logic: if all line sensors read low values,
            # we might be approaching an edge
            if self.px.get_cliff_status(self.line_sensors):
                return EmergencyState.EDGE_DETECTED
        
        # Check for client disconnection if auto-stop is enabled
        if self.auto_stop_enabled:
            if now - self.last_client_seen > self.client_timeout:
                return EmergencyState.CLIENT_DISCONNECTED
        
        # Check for low battery
        if self.battery_level < self.low_battery_threshold:
            # Only trigger once per warning interval
            if now - self.low_battery_last_warning >= self.low_battery_warning_interval:
                self.low_battery_last_warning = now
                return EmergencyState.LOW_BATTERY
        
        return EmergencyState.NONE
    
    async def _handle_emergency(self, emergency):
        """Handle an emergency situation"""
        # Only handle the emergency if it's new or different
        if emergency != self.current_emergency or not self.emergency_active:
            logger.warning(f"Emergency detected: {emergency}")
            self.current_emergency = emergency
            self.emergency_active = True
            self._last_emergency_time = time.time()
            
            # Take emergency action based on the type
            if emergency in [EmergencyState.COLLISION_FRONT, EmergencyState.EDGE_DETECTED]:
                # Stop and back up slightly
                self.px.forward(0)
                await asyncio.sleep(0.1)
                self.px.backward(30)
                await asyncio.sleep(0.5)
                self.px.forward(0)
                
            elif emergency == EmergencyState.COLLISION_REAR:
                # Stop and move forward slightly
                self.px.forward(0)
                await asyncio.sleep(0.1)
                self.px.forward(30)
                await asyncio.sleep(0.5)
                self.px.forward(0)
                
            elif emergency == EmergencyState.CLIENT_DISCONNECTED:
                # Just stop all motion
                self.px.forward(0)
                self.px.set_dir_servo_angle(0)
            
            elif emergency == EmergencyState.LOW_BATTERY:
                # No specific motion action for low battery
                pass
            
            # Call emergency callback if registered
            if self.emergency_callback:
                await self.emergency_callback(emergency)
    
    async def _clear_emergency(self):
        """Clear current emergency state if conditions are safe"""
        # Only clear specific emergencies when conditions are safe
        if self.current_emergency in [EmergencyState.COLLISION_FRONT, EmergencyState.COLLISION_REAR]:
            if self.ultrasonic_distance > self.collision_threshold + 10:  # Add buffer
                self.emergency_active = False
                logger.info(f"Emergency cleared: {self.current_emergency}")
                self.current_emergency = EmergencyState.NONE
        
        elif self.current_emergency == EmergencyState.EDGE_DETECTED:
            if any(sensor > self.edge_detection_threshold for sensor in self.line_sensors):
                self.emergency_active = False
                logger.info(f"Emergency cleared: {self.current_emergency}")
                self.current_emergency = EmergencyState.NONE
        
        elif self.current_emergency == EmergencyState.CLIENT_DISCONNECTED:
            if time.time() - self.last_client_seen < self.client_timeout:
                self.emergency_active = False
                logger.info(f"Emergency cleared: {self.current_emergency}")
                self.current_emergency = EmergencyState.NONE
        
        elif self.current_emergency == EmergencyState.LOW_BATTERY:
            # Low battery is handled by the warning interval
            self.emergency_active = False
            self.current_emergency = EmergencyState.NONE
        
        elif self.current_emergency == EmergencyState.MANUAL_STOP:
            # Manual stops must be explicitly cleared
            pass
    
    def update_motion(self, speed, turn_angle):
        """
        Update the current motion values.
        
        Args:
            speed (float): Speed value (-1.0 to 1.0)
            turn_angle (float): Turn angle (-1.0 to 1.0)
            
        Returns:
            tuple: Modified (speed, turn_angle) if emergency is active
        """
        # Register that we received a command
        self.last_input_time = time.time()
        
        # Store the requested values
        self.current_speed = speed
        self.current_turn = turn_angle
        
        # If emergency is active, override motion commands
        if self.emergency_active:
            if self.current_emergency in [
                EmergencyState.COLLISION_FRONT, 
                EmergencyState.COLLISION_REAR,
                EmergencyState.EDGE_DETECTED,
                EmergencyState.CLIENT_DISCONNECTED,
                EmergencyState.MANUAL_STOP
            ]:
                return 0, turn_angle  # Stop but keep steering
        
        return speed, turn_angle
    
    def register_client_connection(self):
        """Register that a client connected"""
        self.last_client_seen = time.time()
        logger.info("Client connection registered")
    
    def register_client_input(self):
        """Register that a client sent input"""
        self.last_client_seen = time.time()
    
    def client_disconnect(self):
        """Handle client disconnection"""
        self.trigger_emergency(EmergencyState.CLIENT_DISCONNECTED)
    
    def manual_emergency_stop(self):
        """Trigger manual emergency stop"""
        self.trigger_emergency(EmergencyState.MANUAL_STOP)
    
    def clear_manual_stop(self):
        """Clear manual emergency stop"""
        if self.current_emergency == EmergencyState.MANUAL_STOP:
            self.emergency_active = False
            self.current_emergency = EmergencyState.NONE
            logger.info("Manual emergency stop cleared")
    
    def trigger_emergency(self, emergency):
        """Manually trigger a specific emergency"""
        self.current_emergency = emergency
        self.emergency_active = True
        self._last_emergency_time = time.time()
        logger.warning(f"Manually triggered emergency: {emergency}")
    
    def update_battery_level(self, level):
        """Update the battery level"""
        self.battery_level = level
    
    def get_sensor_data(self):
        """Get all sensor data as a dictionary"""
        current_accel = sum(self.accel_history) / max(1, len(self.accel_history))
        
        return {
            "ultrasonic": self.ultrasonic_distance,
            "line_sensors": self.line_sensors,
            "battery": self.battery_level,
            "emergency": {
                "active": self.emergency_active,
                "type": self.current_emergency.name if self.emergency_active else "NONE"
            },
            "speed": self.current_speed,
            "turn": self.current_turn,
            "acceleration": current_accel,
            "settings": {
                "collision_avoidance": self.collision_avoidance_enabled,
                "edge_detection": self.edge_detection_enabled,
                "auto_stop": self.auto_stop_enabled,
                "tracking": self.tracking_enabled,
                "circuit_mode": self.circuit_mode_enabled
            }
        }
    
    def set_collision_avoidance(self, enabled):
        """Enable or disable collision avoidance"""
        self.collision_avoidance_enabled = enabled
        logger.info(f"Collision avoidance {'enabled' if enabled else 'disabled'}")
    
    def set_edge_detection(self, enabled):
        """Enable or disable edge detection"""
        self.edge_detection_enabled = enabled
        logger.info(f"Edge detection {'enabled' if enabled else 'disabled'}")
    
    def set_auto_stop(self, enabled):
        """Enable or disable auto-stop on client disconnection"""
        self.auto_stop_enabled = enabled
        logger.info(f"Auto-stop {'enabled' if enabled else 'disabled'}")
    
    def set_tracking(self, enabled):
        """Enable or disable object tracking"""
        self.tracking_enabled = enabled
        logger.info(f"Object tracking {'enabled' if enabled else 'disabled'}")
    
    def set_circuit_mode(self, enabled):
        """Enable or disable circuit mode"""
        self.circuit_mode_enabled = enabled
        logger.info(f"Circuit mode {'enabled' if enabled else 'disabled'}")