import time
import asyncio
import websockets
import json
import socket
import os
import subprocess
import threading
import psutil
from pathlib import Path
import logging

# Import PicarX hardware interface
from picarx import Picarx

# Import the custom modules
from modules.tts_manager import TTSManager
from modules.sound_manager import SoundManager
from modules.sensor_manager import SensorManager, EmergencyState
from modules.camera_manager import CameraManager, CameraState
from modules.config_manager import ConfigManager
from modules.log_manager import LogManager

# Define project directory
PROJECT_DIR = Path(__file__).parent.parent  # Get ByteRacer root directory
SERVER_HOST = "127.0.0.1:3001"  # Default WebSocket server address

class ByteRacer:
    """Main ByteRacer class that integrates all modules"""
    
    def __init__(self):
        # Initialize logging first
        self.log_manager = LogManager()
        
        # Then initialize hardware
        self.px = Picarx()
        
        # Initialize managers
        self.config_manager = ConfigManager()
        self.tts_manager = TTSManager()
        self.sound_manager = SoundManager()
        self.sensor_manager = SensorManager(self.px, self.handle_emergency)
        self.camera_manager = CameraManager(vflip=False, hflip=False, local=False, web=True)
        
        # WebSocket state
        self.websocket = None
        self.client_connected = False
        self.last_activity_time = time.time()
        self.speaking_ip = False
        self.ip_speaking_task = None
        
        # Motion tracking
        self.last_speed = 0
        self.last_turn = 0
        self.last_acceleration = 0
        self.last_motion_update = time.time()
        
        logging.info("ByteRacer initialized")
    
    async def start(self):
        """Start all managers and begin operation"""
        logging.info("Starting ByteRacer...")
        
        # Start managers
        await self.config_manager.start()
        await self.tts_manager.start()
        await self.sensor_manager.start()
        await self.camera_manager.start(self.handle_camera_status)
        await self.log_manager.start()
        
        # Load settings from config
        await self.apply_config_settings()
        
        # Start TTS introduction
        await self.tts_manager.say("ByteRacer robot controller started successfully", priority=1)
        
        # Start IP announcement if no client is connected
        self.ip_speaking_task = asyncio.create_task(self.announce_ip_periodically())
        
        # Connect to WebSocket server
        url = f"ws://{SERVER_HOST}/ws"
        logging.info(f"Connecting to WebSocket server at {url}")
        await self.connect_to_websocket(url)

    async def stop(self):
        """Stop all services and prepare for shutdown"""
        logging.info("Stopping ByteRacer...")
        
        # Stop IP announcements
        if self.ip_speaking_task:
            self.ip_speaking_task.cancel()
            try:
                await self.ip_speaking_task
            except asyncio.CancelledError:
                pass
        
        # Stop all motion
        self.px.forward(0)
        self.px.set_dir_servo_angle(0)
        self.px.set_cam_pan_angle(0)
        self.px.set_cam_tilt_angle(0)
        
        # Announce shutdown
        await self.tts_manager.say("ByteRacer shutting down", priority=2, blocking=True)
        
        # Stop managers in reverse order
        await self.log_manager.stop()
        await self.camera_manager.stop()
        await self.sensor_manager.stop()
        await self.sound_manager.shutdown()
        await self.tts_manager.stop()
        await self.config_manager.stop()
        
        logging.info("ByteRacer stopped")
    
    async def apply_config_settings(self):
        """Apply settings from config manager to all components"""
        settings = self.config_manager.get()
        
        # Apply sound settings
        self.sound_manager.set_enabled(settings["sound"]["enabled"])
        self.sound_manager.set_volume(settings["sound"]["volume"])
        
        # Apply TTS settings
        self.tts_manager.set_enabled(settings["sound"]["tts_enabled"])
        self.tts_manager.set_volume(settings["sound"]["tts_volume"])
        self.tts_manager.set_language(settings["sound"]["tts_language"])
        
        # Apply camera settings
        restart_camera = self.camera_manager.update_settings(
            vflip=settings["camera"]["vflip"],
            hflip=settings["camera"]["hflip"],
            local=settings["camera"]["local_display"],
            web=settings["camera"]["web_display"]
        )
        
        if restart_camera:
            await self.camera_manager.restart()
        
        # Apply safety settings
        self.sensor_manager.set_collision_avoidance(settings["safety"]["collision_avoidance"])
        self.sensor_manager.set_edge_detection(settings["safety"]["edge_detection"])
        self.sensor_manager.set_auto_stop(settings["safety"]["auto_stop"])
        self.sensor_manager.collision_threshold = settings["safety"]["collision_threshold"]
        self.sensor_manager.edge_detection_threshold = settings["safety"]["edge_threshold"]
        self.sensor_manager.client_timeout = settings["safety"]["client_timeout"]
        
        # Apply special modes
        self.sensor_manager.set_tracking(settings["modes"]["tracking_enabled"])
        self.sensor_manager.set_circuit_mode(settings["modes"]["circuit_mode_enabled"])
        
        logging.info("Applied settings from configuration")
    
    async def save_config_settings(self):
        """Save current settings to config"""
        self.config_manager.save()
        logging.info("Saved settings to configuration")
    
    async def announce_ip_periodically(self):
        """Periodically announce the IP address until a client connects"""
        try:
            while not self.client_connected:
                ip_address = self.get_ip()
                port = SERVER_HOST.split(":")[1] if ":" in SERVER_HOST else "3000"
                
                # Speak the IP address
                await self.tts_manager.say(f"My IP address is {ip_address}. Connect to {ip_address} port {port}", priority=0)
                
                # Check if we've been connected to while speaking
                if self.client_connected:
                    break
                
                # Wait before repeating
                await asyncio.sleep(30)
                
                # Check again if connected before looping
                if self.client_connected:
                    break
            
            logging.info("IP announcement task stopped - client connected")
        except asyncio.CancelledError:
            logging.info("IP announcement task cancelled")
    
    def get_ip(self):
        """Get the robot's IP address"""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        try:
            # This address doesn't need to be reachable
            s.connect(('10.255.255.255', 1))
            ip = s.getsockname()[0]
        except Exception:
            ip = '127.0.0.1'
        finally:
            s.close()
        return ip
    
    async def connect_to_websocket(self, url):
        """Connect to the WebSocket server and handle reconnection"""
        while True:
            try:
                async with websockets.connect(url) as websocket:
                    self.websocket = websocket
                    logging.info(f"Connected to WebSocket server at {url}")
                    
                    # Register as a car
                    register_message = json.dumps({
                        "name": "client_register",
                        "data": {
                            "type": "car",
                            "id": "byteracer-1"
                        },
                        "createdAt": int(time.time() * 1000)
                    })
                    await websocket.send(register_message)
                    
                    # Send initial settings to client
                    await self.send_settings_to_client()
                    
                    # Main message loop
                    while True:
                        try:
                            message = await websocket.recv()
                            await self.handle_message(message, websocket)
                        except websockets.exceptions.ConnectionClosed:
                            logging.warning("WebSocket connection closed")
                            self.client_connected = False
                            break
            except Exception as e:
                logging.error(f"WebSocket connection error: {e}")
                self.websocket = None
                self.client_connected = False
                
                # Announce reconnection attempts via TTS
                await self.tts_manager.say("Connection to control server lost. Attempting to reconnect.", priority=1)
                
                # Wait before retrying
                await asyncio.sleep(5)
    
    async def handle_message(self, message, websocket):
        """Handle messages received from the WebSocket"""
        try:
            data = json.loads(message)
            
            # Log all received message types for debugging
            logging.debug(f"Received message type: {data['name']}")
            
            if data["name"] == "welcome":
                # Handle welcome message
                logging.info(f"Received welcome message, client ID: {data['data']['clientId']}")
                self.client_connected = True
                
                # Clear any pending IP announcements
                self.tts_manager.clear_queue(min_priority=1)
                if self.ip_speaking_task and not self.ip_speaking_task.done():
                    self.ip_speaking_task.cancel()
                
                # Update client connection time for safety monitoring
                self.sensor_manager.register_client_connection()
                
                # Send an initial data update
                await self.send_sensor_data_to_client()
                await self.send_camera_status_to_client()
            
            elif data["name"] == "client_register":
                # Also set client_connected when we receive a register message
                logging.info(f"Received client register message, type: {data['data'].get('type', 'unknown')}")
                self.client_connected = True
                self.sensor_manager.register_client_connection()
                self.last_activity_time = time.time()
                
                # Send initial data
                await self.send_sensor_data_to_client()
                await self.send_camera_status_to_client()
            
            elif data["name"] == "gamepad_input":
                # Handle gamepad input
                await self.handle_gamepad_input(data["data"])
                
                # Update client activity time for safety monitoring
                self.sensor_manager.register_client_input()
                self.last_activity_time = time.time()
                
                # Ensure client is marked as connected when we receive input
                if not self.client_connected:
                    logging.info("Received gamepad input from client, marking as connected")
                    self.client_connected = True
            
            elif data["name"] == "robot_command":
                # Handle robot commands
                command = data["data"].get("command")
                if command:
                    logging.info(f"Received robot command: {command}")
                    result = await self.execute_robot_command(command)
                    await self.send_command_response(result)
            
            elif data["name"] == "battery_request":
                # Handle battery level request
                logging.info("Received battery level request")
                battery_level = self.get_battery_level()
                await self.send_battery_info(battery_level)
            
            elif data["name"] == "settings_update":
                # Handle settings update
                logging.info("Received settings update")
                if "settings" in data["data"]:
                    await self.update_settings(data["data"]["settings"])
                    await self.send_command_response({
                        "success": True,
                        "message": "Settings updated successfully"
                    })
            
            elif data["name"] == "settings":
                # Handle settings request
                logging.info("Received settings request")
                await self.send_settings_to_client()
            
            elif data["name"] == "speak_text":
                # Handle text to speak
                if "text" in data["data"]:
                    text = data["data"]["text"]
                    logging.info(f"Received TTS request: {text}")
                    await self.tts_manager.say(text, priority=1)
                    await self.send_command_response({
                        "success": True,
                        "message": "Text spoken successfully"
                    })
            
            elif data["name"] == "play_sound":
                # Handle sound playback request
                if "sound" in data["data"]:
                    sound_name = data["data"]["sound"]
                    logging.info(f"Received sound playback request: {sound_name}")
                    success = self.sound_manager.play_custom_sound(sound_name)
                    await self.send_command_response({
                        "success": success,
                        "message": f"Sound {'played' if success else 'not found'}: {sound_name}"
                    })
                
            else:
                logging.info(f"Received message of type: {data['name']}")
            
        except json.JSONDecodeError:
            logging.warning(f"Received non-JSON message: {message}")
        except Exception as e:
            logging.error(f"Error processing message: {e}")
    
    async def handle_gamepad_input(self, data):
        """Handle gamepad input data"""
        # Extract values from gamepad data
        turn_value = float(data.get("turn", 0))
        speed_value = float(data.get("speed", 0))
        camera_pan_value = float(data.get("turnCameraX", 0))
        camera_tilt_value = float(data.get("turnCameraY", 0))
        use_button = data.get("use", False)
        
        # Calculate acceleration for sound effects
        now = time.time()
        dt = now - self.last_motion_update
        if dt > 0:
            acceleration = (speed_value - self.last_speed) / dt
        else:
            acceleration = 0
        
        self.last_speed = speed_value
        self.last_turn = turn_value
        self.last_acceleration = acceleration
        self.last_motion_update = now
        
        # Update driving sounds
        self.sound_manager.update_driving_sounds(speed_value, turn_value, acceleration)
        
        # Handle the "use" button for custom sounds
        if use_button and not getattr(self, 'previous_use_state', False):
            self.sound_manager.play_custom_sound('fart')
        
        # Save previous state
        self.previous_use_state = use_button
        
        # Pass inputs through sensor manager to handle safety overrides
        speed_value, turn_value, emergency = self.sensor_manager.update_motion(speed_value, turn_value)

        if emergency:
            return
        
        # Set motor speeds with safety constraints applied
        max_speed = self.config_manager.get("drive.max_speed")
        max_turn = self.config_manager.get("drive.max_turn_angle")
        
        # Apply motor commands
        self.px.set_motor_speed(1, speed_value * max_speed)  # normal motor
        self.px.set_motor_speed(2, speed_value * -max_speed)  # reversed motor
        self.px.set_dir_servo_angle(turn_value * max_turn)
        
        # Set camera angles
        self.px.set_cam_pan_angle(camera_pan_value * 90)
        
        # Handle camera tilt with different ranges for up/down
        if camera_tilt_value >= 0:
            self.px.set_cam_tilt_angle(camera_tilt_value * 65)
        else:
            self.px.set_cam_tilt_angle(camera_tilt_value * 35)
    
    async def handle_emergency(self, emergency):
        """Handle emergency situations"""
        # Play alert sound
        self.sound_manager.play_alert("emergency")
        
        # Provide feedback via TTS
        if emergency == EmergencyState.COLLISION_FRONT:
            await self.tts_manager.say("Emergency stop. Obstacle detected ahead. Backing up.", priority=2)
        elif emergency == EmergencyState.EDGE_DETECTED:
            await self.tts_manager.say("Emergency stop. Edge detected. Backing up.", priority=2)
        elif emergency == EmergencyState.CLIENT_DISCONNECTED:
            await self.tts_manager.say("Emergency stop. Client disconnected.", priority=2)
        elif emergency == EmergencyState.LOW_BATTERY:
            await self.tts_manager.say(f"Warning. Battery level low. Please recharge soon.", priority=2)
        elif emergency == EmergencyState.MANUAL_STOP:
            await self.tts_manager.say("Emergency stop activated.", priority=2)
        
        # Send emergency status to client if connected
        await self.send_sensor_data_to_client()
    
    async def handle_camera_status(self, status):
        """Handle camera status updates"""
        logging.info(f"Camera status update: {status['state']}")
        
        if status['state'] == CameraState.ERROR.name:
            # Notify via TTS
            await self.tts_manager.say("Camera error detected.", priority=1)
        
        elif status['state'] == CameraState.RESTARTING.name:
            # Notify via TTS
            await self.tts_manager.say("Restarting camera.", priority=1)
        
        # Send status to client
        await self.send_camera_status_to_client()
    
    async def update_settings(self, settings):
        """Update settings based on client request"""
        if "sound" in settings:
            sound = settings["sound"]
            if "enabled" in sound:
                self.config_manager.set("sound.enabled", sound["enabled"])
                self.sound_manager.set_enabled(sound["enabled"])
            
            if "volume" in sound:
                self.config_manager.set("sound.volume", sound["volume"])
                self.sound_manager.set_volume(sound["volume"])
            
            if "tts_enabled" in sound:
                self.config_manager.set("sound.tts_enabled", sound["tts_enabled"])
                self.tts_manager.set_enabled(sound["tts_enabled"])
            
            if "tts_volume" in sound:
                self.config_manager.set("sound.tts_volume", sound["tts_volume"])
                self.tts_manager.set_volume(sound["tts_volume"])
        
        if "camera" in settings:
            camera = settings["camera"]
            restart_needed = False
            
            if "vflip" in camera:
                self.config_manager.set("camera.vflip", camera["vflip"])
                restart_needed |= self.camera_manager.update_settings(vflip=camera["vflip"])
            
            if "hflip" in camera:
                self.config_manager.set("camera.hflip", camera["hflip"])
                restart_needed |= self.camera_manager.update_settings(hflip=camera["hflip"])
            
            if restart_needed:
                await self.camera_manager.restart()
        
        if "safety" in settings:
            safety = settings["safety"]
            if "collision_avoidance" in safety:
                self.config_manager.set("safety.collision_avoidance", safety["collision_avoidance"])
                self.sensor_manager.set_collision_avoidance(safety["collision_avoidance"])
            
            if "edge_detection" in safety:
                self.config_manager.set("safety.edge_detection", safety["edge_detection"])
                self.sensor_manager.set_edge_detection(safety["edge_detection"])
            
            if "auto_stop" in safety:
                self.config_manager.set("safety.auto_stop", safety["auto_stop"])
                self.sensor_manager.set_auto_stop(safety["auto_stop"])
        
        if "modes" in settings:
            modes = settings["modes"]
            if "tracking_enabled" in modes:
                self.config_manager.set("modes.tracking_enabled", modes["tracking_enabled"])
                self.sensor_manager.set_tracking(modes["tracking_enabled"])
            
            if "circuit_mode_enabled" in modes:
                self.config_manager.set("modes.circuit_mode_enabled", modes["circuit_mode_enabled"])
                self.sensor_manager.set_circuit_mode(modes["circuit_mode_enabled"])
        
        # Save settings
        await self.save_config_settings()
    
    async def execute_robot_command(self, command):
        """Handle system commands and provide feedback"""
        result = {"success": False, "message": "Unknown command"}
        
        try:
            if command == "restart_robot":
                # Restart the entire system
                await self.tts_manager.say("Restarting system. Please wait.", priority=2, blocking=True)
                result = {"success": True, "message": "Rebooting system..."}
                # Schedule system reboot after response is sent
                threading.Timer(2.0, lambda: subprocess.run("sudo reboot", shell=True)).start()
                
            elif command == "stop_robot":
                # Shutdown the system
                await self.tts_manager.say("Shutting down system. Goodbye!", priority=2, blocking=True)
                result = {"success": True, "message": "Shutting down system..."}
                threading.Timer(2.0, lambda: subprocess.run("sudo shutdown -h now", shell=True)).start()
                
            elif command == "restart_all_services":
                # Restart all three services
                await self.tts_manager.say("Restarting all services. Please wait.", priority=2, blocking=True)
                success = subprocess.run(
                    f"cd {PROJECT_DIR} && sudo bash ./byteracer/scripts/restart_services.sh",
                    shell=True,
                    check=False
                ).returncode == 0
                
                result["success"] = success
                result["message"] = "All services restarted" if success else "Failed to restart services"
                
            elif command == "restart_websocket":
                # Restart just the WebSocket service
                await self.tts_manager.say("Restarting WebSocket service.", priority=1, blocking=True)
                success = subprocess.run(
                    f"cd {PROJECT_DIR} && sudo bash ./byteracer/scripts/restart_websocket.sh",
                    shell=True,
                    check=False
                ).returncode == 0
                
                result["success"] = success
                result["message"] = "WebSocket service restarted" if success else "Failed to restart WebSocket service"
                
            elif command == "restart_web_server":
                # Restart just the web server
                await self.tts_manager.say("Restarting web server.", priority=1, blocking=True)
                success = subprocess.run(
                    f"cd {PROJECT_DIR} && sudo bash ./byteracer/scripts/restart_web_server.sh",
                    shell=True,
                    check=False
                ).returncode == 0
                
                result["success"] = success
                result["message"] = "Web server restarted" if success else "Failed to restart web server"
                
            elif command == "restart_python_service":
                # Restart just the Python service
                await self.tts_manager.say("Restarting Python controller. Goodbye!", priority=2, blocking=True)
                result["success"] = True
                result["message"] = "Python service will restart"
                
                # Exit Python script - systemd or screen will restart it
                threading.Timer(1.0, lambda: os._exit(0)).start()
                
            elif command == "restart_camera_feed":
                # Restart camera feed
                await self.tts_manager.say("Restarting camera feed.", priority=1)
                success = await self.camera_manager.restart()
                
                result["success"] = success
                result["message"] = "Camera feed restarted" if success else "Failed to restart camera feed"
                
            elif command == "check_for_updates":
                # Check for updates
                await self.tts_manager.say("Checking for updates. Please wait.", priority=1, blocking=True)
                success = subprocess.run(
                    f"cd {PROJECT_DIR} && sudo bash ./byteracer/scripts/update.sh",
                    shell=True,
                    check=False
                ).returncode == 0
                
                result["success"] = success
                result["message"] = "Update check completed" if success else "Failed to check for updates"
                
            elif command == "emergency_stop":
                # Trigger emergency stop
                self.sensor_manager.manual_emergency_stop()
                result["success"] = True
                result["message"] = "Emergency stop activated"
                
            elif command == "clear_emergency":
                # Clear emergency stop
                self.sensor_manager.clear_manual_stop()
                result["success"] = True
                result["message"] = "Emergency stop cleared"
                
            else:
                result["message"] = f"Unknown command: {command}"
                
        except Exception as e:
            logging.error(f"Error executing command {command}: {e}")
            result["message"] = f"Error: {str(e)}"
            
        return result
    
    def get_battery_level(self):
        """Get the current battery level"""
        from robot_hat import get_battery_voltage
        
        # Get the battery voltage
        voltage = get_battery_voltage()
        
        # Calculate the percentage based on the voltage range
        if voltage >= 7.8:
            level = 100
        elif voltage >= 6.7:
            level = int((voltage - 6.7) / (7.8 - 6.7) * 100)
        else:
            level = 0
        
        # Update sensor manager with battery level
        self.sensor_manager.update_battery_level(level)
        
        return level
    
    async def send_battery_info(self, level):
        """Send battery information to the client"""
        if self.websocket:
            try:
                await self.websocket.send(json.dumps({
                    "name": "battery_info",
                    "data": {
                        "level": level,
                        "timestamp": int(time.time() * 1000)
                    },
                    "createdAt": int(time.time() * 1000)
                }))
                logging.debug(f"Sent battery info: {level}%")
            except Exception as e:
                logging.error(f"Error sending battery info: {e}")
    
    async def send_sensor_data_to_client(self):
        """Send sensor data to the client"""
        if self.websocket and self.client_connected:
            try:
                # Get raw sensor data
                sensor_data = self.sensor_manager.get_sensor_data()
                
                # Transform sensor data to match client expectations
                transformed_data = {
                    "ultrasonicDistance": sensor_data["ultrasonic"],
                    "lineFollowLeft": sensor_data["line_sensors"][0],
                    "lineFollowMiddle": sensor_data["line_sensors"][1],
                    "lineFollowRight": sensor_data["line_sensors"][2],
                    "emergencyState": sensor_data["emergency"]["type"] if sensor_data["emergency"]["active"] else None,
                    "batteryLevel": sensor_data["battery"],
                    "isCollisionAvoidanceActive": sensor_data["settings"]["collision_avoidance"],
                    "isEdgeDetectionActive": sensor_data["settings"]["edge_detection"],
                    "isAutoStopActive": sensor_data["settings"]["auto_stop"],
                    "isTrackingActive": sensor_data["settings"]["tracking"],
                    "isCircuitModeActive": sensor_data["settings"]["circuit_mode"],
                    "clientConnected": self.client_connected,
                    "lastClientActivity": int(self.last_activity_time * 1000),  # Convert to milliseconds
                    "speed": sensor_data["speed"],  # Add speed value
                    "turn": sensor_data["turn"],    # Add turn value
                    "acceleration": sensor_data["acceleration"]  # Add acceleration value
                }
                
                await self.websocket.send(json.dumps({
                    "name": "sensor_data",
                    "data": transformed_data,
                    "createdAt": int(time.time() * 1000)
                }))
                logging.debug("Sent sensor data to client")
            except Exception as e:
                logging.error(f"Error sending sensor data: {e}")
    
    async def send_camera_status_to_client(self):
        """Send camera status to the client"""
        if self.websocket and self.client_connected:
            try:
                camera_status = self.camera_manager.get_status()
                
                await self.websocket.send(json.dumps({
                    "name": "camera_status",
                    "data": camera_status,
                    "createdAt": int(time.time() * 1000)
                }))
                logging.debug("Sent camera status to client")
            except Exception as e:
                logging.error(f"Error sending camera status: {e}")
    
    async def send_command_response(self, result):
        """Send command response to the client"""
        if self.websocket and self.client_connected:
            try:
                await self.websocket.send(json.dumps({
                    "name": "command_response",
                    "data": result,
                    "createdAt": int(time.time() * 1000)
                }))
                logging.debug(f"Sent command response: {result['message']}")
            except Exception as e:
                logging.error(f"Error sending command response: {e}")
    
    async def send_settings_to_client(self):
        """Send current settings to the client"""
        if self.websocket and self.client_connected:
            try:
                settings = self.config_manager.get()
                
                await self.websocket.send(json.dumps({
                    "name": "settings",
                    "data": {"settings": settings},
                    "createdAt": int(time.time() * 1000)
                }))
                logging.debug("Sent settings to client")
            except Exception as e:
                logging.error(f"Error sending settings: {e}")
    
    async def periodic_tasks(self):
        """Run periodic tasks like sensor updates"""
        logging.info("Starting periodic tasks loop")
        task_counter = 0
        while True:
            try:
                task_counter += 1
                # Log every 10 iterations to avoid excessive logging
                if task_counter % 10 == 0:
                    logging.info(f"Periodic tasks running (iteration {task_counter})")
                
                # Send sensor data every second if client is connected
                if self.client_connected:
                    try:
                        await self.send_sensor_data_to_client()
                        logging.debug("Periodic sensor data sent")
                    except Exception as e:
                        logging.error(f"Error sending periodic sensor data: {e}")
                else:
                    logging.debug("Client not connected, skipping sensor data")
                
                # Always use a consistent update interval, don't slow down when idle
                # This ensures continuous data flow
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                logging.info("Periodic tasks cancelled")
                break
            except Exception as e:
                logging.error(f"Error in periodic tasks: {e}", exc_info=True)
                await asyncio.sleep(2)  # Shorter sleep on error

async def main():
    """Main entry point for ByteRacer"""
    try:
        # Create and start ByteRacer
        robot = ByteRacer()
        await robot.start()
        
        # Start periodic task for sending updates and ensure it's running
        logging.info("Creating periodic task for sensor updates")
        periodic_task = asyncio.create_task(robot.periodic_tasks())
        
        # Register task exception callback to detect if it fails
        def handle_task_exception(task):
            try:
                # This will re-raise any exception that occurred in the task
                task.result()
            except Exception as e:
                logging.critical(f"Periodic task failed with error: {e}", exc_info=True)
                # Restart the task
                asyncio.create_task(robot.periodic_tasks())
                
        periodic_task.add_done_callback(handle_task_exception)
        
        # Wait for keyboard interrupt
        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            logging.info("Keyboard interrupt received, shutting down")
        finally:
            # Cancel periodic task
            periodic_task.cancel()
            try:
                await periodic_task
            except asyncio.CancelledError:
                pass
            
            # Stop ByteRacer
            await robot.stop()
    
    except Exception as e:
        logging.critical(f"Fatal error: {e}")
        raise

if __name__ == "__main__":
    try:
        print("ByteRacer starting...")
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
    except Exception as e:
        print(f"Fatal error: {e}")
    finally:
        print("ByteRacer offline.")
