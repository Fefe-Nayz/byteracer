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
    EDGE_DETECTED = auto()
    CLIENT_DISCONNECTED = auto()
    LOW_BATTERY = auto()
    MANUAL_STOP = auto()

class RobotState(Enum):
    """Enum representing different robot states"""
    WAITING_FOR_CLIENT = auto() # The robot just started and is waiting for a client to connect to the website. The ony thing it can do is tell it's IP address.
    WAITING_FOR_INPUT = auto() # The client has reached the website, it can control some aspects of the robot (like settings, sounds, tts and gpt etc.) but it has not still connected a controller to the client device or it is still not used so it is sending no input data.
    CONTROLLED_BY_CLIENT = auto() # The client has connected a controller to the client device and is sending input data to the robot at 20hz. The robot is controlled by the client. If the input stream stops or if the client disconnects either it's controller or completely closes the website and if the robot was moving then we should trigger the emergency stop to prevent the robot from crashing into something. In this state the client can control all aspects of the robot (like settings, sounds, tts and gpt etc.) and it is controlling the robot.
    EMERGENCY_CONTROL = auto() # The robot is in an emergency state. The robot is taking over some part of the control over the client to avoid crash but depending on the emergency the client can still control some movements of the robot and it can still control all the other aspects that are not related to the robot movement. 
    GPT_CONTROLLED = auto() # This state is used when the client is triggering a chatGPT prompt. During the ai awnser and execution of the AI response nothing can alter it (excpet a force stop of the sequence by the client). When the robot is controlled by AI, no emergency can be triggered, the client controls inputs are ignored but the client can still control all other aspects of the robot (like settings, sounds, tts and gpt etc.).
    CIRCUIT_MODE = auto() # The robot is in circuit mode. The robot is controlled by the client but only specific emergency situations can be triggered. The robot will use it's sensor of line following not to detect cliffs but the edges of the road and preventing the user to go outside the sircuit, the proximity sensor and stop emergency are still here and we are adding computer vision, if the robot detects signs or traffic lights the robot will make sure to enforce the rules of the road on the client. If for example the client tries to cross a no way street or a red light the robot will stop and only allow inputs from the client that are going to respect the road rules. If the robot detects a sign or traffic light it's camera will lock on it to be sure not to loose track of it, the client won't be able to move the head.
    DEMO_MODE = auto() # The robot is doing pre-registered actions and tts to demo it capabilities. The user inputs are not taken into account. The emergency of collision and cliff are active
    TRACKING_MODE = auto() # The robot is going arround (by itself) until he detects a person. When it detects a person the head will lock on it and the robot will follow the person. The robot will use it's camera to detect the person and the line following sensors to avoid cliffs. The robot will not be able to move if it detects a cliff or an obstacle in front of it. The user inputs are not taken into account. The emergency of collision and cliff are active

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
        self._emergency_cooldown = 0.1  # Seconds
        
        # Sensor readings
        self.ultrasonic_distance = float('inf')  # In cm
        self.line_sensors = [0, 0, 0]  # Left, center, right
        self.last_input_time = time.time()
        self.last_client_seen = time.time()
        self.battery_level = 100
        
        # Safety thresholds
        self.collision_threshold = 20  # cm
        # Hardcoded safe distance buffer - not configurable via settings
        self.safe_distance_buffer = 10  # Additional cm to add to collision threshold for safe distance
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
        
        # Client state
        self.client_ever_connected = False
        self.client_currently_connected = False

        # Edge recovery state
        self.edge_recovery_start_time = 0
        self.edge_recovery_min_time = 0.5  # Minimum backup time after edge is no longer detected

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
        self._emergency_task = None
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
        
        if self._emergency_task and not self._emergency_task.done():
            self._emergency_task.cancel()
            try:
                await self._emergency_task
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
                
                # Check for emergencies - only if client has connected at least once
                if self.client_ever_connected:
                    emergency = self._check_emergency_conditions()
                    
                    # Handle any detected emergency
                    if emergency != EmergencyState.NONE and emergency != self.current_emergency:
                        # Call emergency callback immediately
                        if self.emergency_callback:
                            # Create a new task for the callback so it runs in parallel
                            asyncio.create_task(self.emergency_callback(emergency))
                        
                        # Start the emergency handling process
                        self._emergency_task = asyncio.create_task(self._handle_emergency(emergency))
                    elif self.emergency_active:
                        # Check if we can clear the emergency
                        await self._check_emergency_clearance()
                
                # Short delay to avoid CPU overuse
                await asyncio.sleep(0.05)  # Slightly faster updates for better responsiveness
                
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
        
        # Only check emergencies if client is currently connected
        if not self.client_currently_connected and self.auto_stop_enabled:
            # Exception: check for client disconnection only if client was previously connected
            if self.client_ever_connected and now - self.last_client_seen > self.client_timeout:
                return EmergencyState.CLIENT_DISCONNECTED
            return EmergencyState.NONE
        
        # Check for obstacles if collision avoidance is enabled
        if self.collision_avoidance_enabled:
            # Modified to trigger on close obstacles regardless of motion
            # This helps respond to objects moving toward a stationary robot
            if self.ultrasonic_distance < self.collision_threshold:
                return EmergencyState.COLLISION_FRONT
        
        # Check for edges if edge detection is enabled
        if self.edge_detection_enabled:
            # Simple edge detection logic: if all line sensors read low values,
            # we might be approaching an edge
            if self.px.get_cliff_status(self.line_sensors):
                return EmergencyState.EDGE_DETECTED
        
        # Check for client disconnection if auto-stop is enabled
        if self.auto_stop_enabled and self.client_ever_connected:
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
        # Mark emergency as active
        logger.warning(f"Emergency detected: {emergency}")
        self.current_emergency = emergency
        self.emergency_active = True
        self._last_emergency_time = time.time()
        
        try:
            # Take emergency action based on the type
            if emergency == EmergencyState.COLLISION_FRONT:
                # For collision, we want to maintain a minimum safe distance
                # Use fixed 5cm buffer beyond the collision threshold
                safe_distance = self.collision_threshold + 5
                
                # Only stop immediately if we're moving forward
                if self.current_speed > 0:
                    self.px.forward(0)
                    await asyncio.sleep(0.05)
                
                # Start backing up immediately at a consistent speed
                backup_speed = 30  # Use a higher consistent speed for smoother backup
                
                # Back up continuously until reaching safe distance
                while self.emergency_active and self.current_emergency == EmergencyState.COLLISION_FRONT:
                    # Get latest distance reading
                    await self._update_sensor_readings()
                    
                    # If we've reached safe distance, stop backing up
                    if self.ultrasonic_distance > safe_distance:
                        logger.info(f"Safe distance reached: {self.ultrasonic_distance} cm > {safe_distance} cm")
                        break
                    
                    # Continue backing up - don't rely on user motion control
                    # This ensures the robot always moves away from obstacles
                    self.px.backward(backup_speed)
                    
                    # Allow other tasks to run and check distance frequently
                    await asyncio.sleep(0.05)
                
                # Stop after reaching safe distance
                self.px.forward(0)
                logger.info(f"Collision emergency - Backup complete - reached distance: {self.ultrasonic_distance} cm")
                
                # Clear emergency
                if self.current_emergency == EmergencyState.COLLISION_FRONT:
                    self.emergency_active = False
                    self.current_emergency = EmergencyState.NONE
                
            elif emergency == EmergencyState.EDGE_DETECTED:
                # Record when we start backing up
                self.edge_recovery_start_time = time.time()
                
                # Start backing up - continuous motion
                self.px.backward(100)
                
                # Continue backing up until edge is no longer detected plus a small buffer time
                last_edge_clear_time = 0
                
                while self.emergency_active and self.current_emergency == EmergencyState.EDGE_DETECTED:
                    # Update sensor readings
                    await self._update_sensor_readings()
                    
                    # Check if edge is still detected
                    edge_detected = self.px.get_cliff_status(self.line_sensors)
                    
                    if not edge_detected:
                        # If this is the first time we're clear, record the time
                        if last_edge_clear_time == 0:
                            last_edge_clear_time = time.time()
                        
                        # If we've been clear for the minimum buffer time, stop backing up
                        if time.time() - last_edge_clear_time >= self.edge_recovery_min_time:
                            break
                    else:
                        # Reset the clear time if edge is detected again
                        last_edge_clear_time = 0
                    
                    # Keep backing up - don't rely on user motion control
                    self.px.backward(100)
                    
                    # Check frequently but allow other tasks to run
                    await asyncio.sleep(0.05)
                
                # Stop after reaching safe position
                self.px.forward(0)
                logger.info("Edge emergency - Recovery complete")
                
                # Clear emergency
                if self.current_emergency == EmergencyState.EDGE_DETECTED:
                    self.emergency_active = False
                    self.current_emergency = EmergencyState.NONE
                
            elif emergency == EmergencyState.CLIENT_DISCONNECTED:
                # Just stop all motion
                self.px.forward(0)
                self.px.set_dir_servo_angle(0)
                
                # Wait until client reconnects or emergency is cleared manually
                while self.emergency_active and self.current_emergency == EmergencyState.CLIENT_DISCONNECTED:
                    await asyncio.sleep(0.5)
            
            elif emergency == EmergencyState.LOW_BATTERY:
                # No specific motion action for low battery
                # Just wait for warning interval to pass
                await asyncio.sleep(self.low_battery_warning_interval)
                self.emergency_active = False
                self.current_emergency = EmergencyState.NONE
            
            elif emergency == EmergencyState.MANUAL_STOP:
                # Manual stop just stops motion and waits for explicit clear
                self.px.forward(0)
                self.px.set_dir_servo_angle(0)
                
                # Wait until manual stop is cleared
                while self.emergency_active and self.current_emergency == EmergencyState.MANUAL_STOP:
                    await asyncio.sleep(0.5)
        
        except asyncio.CancelledError:
            logger.info(f"Emergency handling for {emergency.name} was cancelled")
            # Make sure to stop if we're cancelled
            self.px.forward(0)
            raise
        except Exception as e:
            logger.error(f"Error in emergency handling for {emergency.name}: {e}")
            # Make sure to stop on errors
            self.px.forward(0)
        finally:
            # Only clear the emergency if it hasn't been changed to a different one
            # and wasn't already cleared in the handler
            if self.current_emergency == emergency and self.emergency_active:
                logger.info(f"Emergency handling completed for: {emergency.name}")
                self.emergency_active = False
                self.current_emergency = EmergencyState.NONE
    
    async def _check_emergency_clearance(self):
        """Check if current emergency conditions are cleared"""
        # Only apply to automatic clearance conditions
        if self.current_emergency == EmergencyState.COLLISION_FRONT:
            # Clear if distance is now safe
            safe_distance = self.collision_threshold + self.safe_distance_buffer
            if self.ultrasonic_distance > safe_distance:
                logger.info(f"Emergency cleared: {self.current_emergency}")
                self.emergency_active = False
                self.current_emergency = EmergencyState.NONE
        
        elif self.current_emergency == EmergencyState.EDGE_DETECTED:
            # Already handled in _handle_emergency
            pass
        
        elif self.current_emergency == EmergencyState.CLIENT_DISCONNECTED:
            # Clear if client is seen again
            if time.time() - self.last_client_seen < self.client_timeout:
                logger.info(f"Emergency cleared: {self.current_emergency}")
                self.emergency_active = False
                self.current_emergency = EmergencyState.NONE
        
        elif self.current_emergency == EmergencyState.LOW_BATTERY:
            # Already handled in _handle_emergency
            pass
    
    def update_motion(self, speed, turn_angle):
        """
        Update the current motion values.
        
        Args:
            speed (float): Speed value (-1.0 to 1.0)
            turn_angle (float): Turn angle (-1.0 to 1.0)
            
        Returns:
            tuple: Modified (speed, turn_angle, emergency_active)
        """
        # Register that we received a command
        self.last_input_time = time.time()
        
        # Store the requested values
        self.current_speed = speed
        self.current_turn = turn_angle
        
        # Handle emergency overrides based on emergency type
        if self.emergency_active:
            if self.current_emergency == EmergencyState.COLLISION_FRONT:
                # For collision, only prevent forward motion
                if speed >= -30:
                    speed = -30
                # Allow steering and backward motion
            
            elif self.current_emergency == EmergencyState.EDGE_DETECTED:
                # For edge detection, completely control wheel speed for safety
                # But allow steering to continue working
                speed = -0.5  # Force backing up
            
            elif self.current_emergency in [EmergencyState.CLIENT_DISCONNECTED, EmergencyState.MANUAL_STOP]:
                # Complete stop for these emergencies
                speed = 0
                turn_angle = 0  # Also stop steering
            
            elif self.current_emergency == EmergencyState.LOW_BATTERY:
                # For low battery, still allow motion but at reduced power
                speed = speed * 0.5
        
        return speed, turn_angle, self.emergency_active
    
    def update_client_status(self, connected, ever_connected):
        """Update the client connection status"""
        self.client_currently_connected = connected
        if ever_connected:
            self.client_ever_connected = True
    
    def register_client_connection(self):
        """Register that a client connected"""
        self.last_client_seen = time.time()
        self.client_ever_connected = True
        self.client_currently_connected = True
        logger.info("Client connection registered")
    
    def register_client_input(self):
        """Register that a client sent input"""
        self.last_client_seen = time.time()
    
    def client_disconnect(self):
        """Handle client disconnection"""
        self.client_currently_connected = False
        if self.client_ever_connected:
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
        
        # Start emergency handling in a task
        if self._emergency_task and not self._emergency_task.done():
            self._emergency_task.cancel()
        self._emergency_task = asyncio.create_task(self._handle_emergency(emergency))
        
        # Call callback immediately if it exists
        if self.emergency_callback:
            asyncio.create_task(self.emergency_callback(emergency))
            
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

    def set_edge_detection_threshold(self, threshold):
        """Set the edge detection threshold"""
        self.edge_detection_threshold = threshold
        self.px.set_cliff_reference([threshold] * 1000)
        logger.info(f"Edge detection threshold set to {threshold}")
    
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
    
    def set_demo_mode(self, enabled):
        """Enable or disable demo mode"""
        # Implementation depends on what demo mode does
        logger.info(f"Demo mode {'enabled' if enabled else 'disabled'}")