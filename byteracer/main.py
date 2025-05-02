import time
import asyncio
import websockets
import json
import socket
import os
import subprocess
import threading
import psutil
import sys
from pathlib import Path
import logging

# Import PicarX hardware interface
from picarx import Picarx

# Import the custom modules
from modules.tts_manager import TTSManager
from modules.sound_manager import SoundManager
from modules.sensor_manager import SensorManager, EmergencyState, RobotState
from modules.camera_manager import CameraManager, CameraState
from modules.config_manager import ConfigManager
from modules.log_manager import LogManager
from modules.gpt_manager import GPTManager
from modules.network_manager import NetworkManager
from modules.aicamera_manager import AICameraCameraManager

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
        
        # Initialize config manager first to get camera settings
        self.config_manager = ConfigManager()
        
        # Get camera settings from config
        camera_config = self.config_manager.get("camera")
        vflip = camera_config.get("vflip", False)
        hflip = camera_config.get("hflip", False)
        local_display = camera_config.get("local_display", False)
        web_display = camera_config.get("web_display", True)
        camera_size = tuple(camera_config.get("camera_size", [1920, 1080]))
        
        # Initialize managers - order matters for dependencies
        self.sound_manager = SoundManager()  # Initialize sound manager first
        self.tts_manager = TTSManager(sound_manager=self.sound_manager)  # Pass sound manager to TTS manager
        self.sensor_manager = SensorManager(self.px, self.handle_emergency)
        
        # Initialize camera with config settings directly
        self.camera_manager = CameraManager(
            vflip=vflip, 
            hflip=hflip, 
            local=local_display, 
            web=web_display, 
            camera_size=camera_size
        )

        self.aicamera_manager = AICameraCameraManager(self.px, self.sensor_manager, self.camera_manager)
        self.network_manager = NetworkManager()
        self.gpt_manager = GPTManager(self.px, self.camera_manager, self.tts_manager, self.sound_manager, self.sensor_manager, self.config_manager, self.aicamera_manager)
        
        # Initialize audio manager for microphone streaming
        from modules.audio_manager import AudioManager
        self.audio_manager = AudioManager()
        
        # WebSocket state
        self.websocket = None
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
        await self.audio_manager.start()
        
        # Initialize network manager
        self.network_manager = NetworkManager()
        
        # Load settings from config
        await self.apply_config_settings()
        
        # Start TTS introduction
        await self.tts_manager.say("ByteRacer robot controller started successfully", priority=1, blocking=True)
        
        # Start IP announcement if no client is connected
        self.ip_speaking_task = asyncio.create_task(self.announce_ip_periodically())
        
        # Connect to WebSocket server in a separate task so it doesn't block
        url = f"ws://{SERVER_HOST}/ws"
        logging.info(f"Connecting to WebSocket server at {url}")
        self.websocket_task = asyncio.create_task(self.connect_to_websocket(url))
        
        # Return so other code can run
        return

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
        await self.audio_manager.stop()
        
        logging.info("ByteRacer stopped")
    
    async def apply_config_settings(self):
        """Apply settings from config manager to all components"""
        settings = self.config_manager.get()
        
        # Apply sound settings - updating with detailed volume controls
        self.sound_manager.set_enabled(settings["sound"]["enabled"])
        
        # Apply master volume
        self.sound_manager.set_volume(settings["sound"]["volume"])
        
        # Apply sound effects master volume
        if "sound_volume" in settings["sound"]:
            self.sound_manager.set_sound_volume(settings["sound"]["sound_volume"])
        
        # Apply category-specific volumes
        if "driving_volume" in settings["sound"]:
            self.sound_manager.set_category_volume("driving", settings["sound"]["driving_volume"])
        
        if "alert_volume" in settings["sound"]:
            self.sound_manager.set_category_volume("alert", settings["sound"]["alert_volume"])
        
        if "custom_volume" in settings["sound"]:
            self.sound_manager.set_category_volume("custom", settings["sound"]["custom_volume"])
        
        if "voice_volume" in settings["sound"]:
            self.sound_manager.set_category_volume("voice", settings["sound"]["voice_volume"])
        
        # Apply TTS settings
        self.tts_manager.set_enabled(settings["sound"]["tts_enabled"])
        self.tts_manager.set_language(settings["sound"]["tts_language"])
        
        # Apply TTS volume settings
        self.tts_manager.set_volume(settings["sound"]["tts_volume"])
        
        # Apply TTS audio gain if available
        if "tts_audio_gain" in settings["sound"]:
            self.tts_manager.set_tts_audio_gain(settings["sound"]["tts_audio_gain"])
        
        if "user_tts_volume" in settings["sound"]:
            self.tts_manager.set_user_tts_volume(settings["sound"]["user_tts_volume"])
        
        if "system_tts_volume" in settings["sound"]:
            self.tts_manager.set_system_tts_volume(settings["sound"]["system_tts_volume"])
        
        if "emergency_tts_volume" in settings["sound"]:
            self.tts_manager.set_emergency_tts_volume(settings["sound"]["emergency_tts_volume"])

        # Apply safety settings
        self.sensor_manager.set_collision_avoidance(settings["safety"]["collision_avoidance"])
        self.sensor_manager.set_edge_detection(settings["safety"]["edge_detection"])
        self.sensor_manager.set_auto_stop(settings["safety"]["auto_stop"])
        self.sensor_manager.collision_threshold = settings["safety"]["collision_threshold"]
        self.sensor_manager.edge_detection_threshold = settings["safety"]["edge_threshold"]
        self.sensor_manager.client_timeout = settings["safety"]["client_timeout"]

        
        logging.info("Applied settings from configuration")
    
    async def save_config_settings(self):
        """Save current settings to config"""
        self.config_manager.save()
        logging.info("Saved settings to configuration")
    
    async def announce_ip_periodically(self):
        """Periodically announce the IP address until a client connects"""
        try:
            # Track previous network state
            previous_ip = None
            previous_mode = None
            first_run = True

            while True:
                try:
                    # Get current network status
                    network_status = await self.network_manager.get_connection_status()
                    current_ips = network_status.get("ip_addresses", {})
                    current_mode = "ap" if network_status.get("ap_mode_active", False) else "wifi"
                    port = "3000"
                    
                    # Get the primary interface IP
                    wifi_interface = self.network_manager.wifi_interface
                    current_ip = current_ips.get(wifi_interface, "unknown")

                    logging.info(f"Current IP: {current_ip}, Mode: {current_mode}")
                    
                    # Check if IP or mode has changed
                    ip_changed = current_ip != previous_ip and previous_ip is not None
                    mode_changed = current_mode != previous_mode and previous_mode is not None
                    
                    # Determine if we need to make an announcement
                    should_announce = False
                    
                    # Always announce on first run or when not connected
                    if first_run or not self.sensor_manager.robot_state.isConnected():
                        should_announce = True
                        first_run = False
                    # Announce if network changed while connected
                    elif ip_changed or mode_changed:
                        logging.info(f"Network changed: IP: {current_ip} (was {previous_ip}), Mode: {current_mode} (was {previous_mode})")
                        self.sensor_manager.robot_state = RobotState.STANDBY
                        should_announce = True
                        
                        # Update client status in sensor manager
                        # self.sensor_manager.update_client_status(False, True)
                    
                    # Make announcement if needed
                    if should_announce:
                        # Update previous state
                        previous_ip = current_ip
                        previous_mode = current_mode
                        
                        # Prepare message based on mode
                        if current_mode == "ap":
                            ap_name = network_status.get("ap_ssid", "ByteRacer")
                            message = f"Access point mode active. Connect to WiFi network {ap_name}, then visit {current_ip} port {port} in your browser."
                        else:
                            message = f"WiFi mode active. My IP address is {current_ip}. Connect to {current_ip} port {port} in your browser."
                        
                        # Speak the message
                        await self.tts_manager.say(message, priority=1)
                        logging.info(f"Announced IP: {current_ip}, Mode: {current_mode}")
                    
                    # Wait before checking again
                    if self.sensor_manager.robot_state == RobotState.MANUAL_CONTROL:
                        # Check less frequently when client is connected
                        await asyncio.sleep(60)
                    else:
                        # Check more frequently when no client is connected
                        await asyncio.sleep(30)
                        
                except Exception as e:
                    logging.error(f"Error in IP announcement task: {e}")
                    await asyncio.sleep(30)  # Wait before retrying on error
        except asyncio.CancelledError:
            logging.info("IP announcement task cancelled")
    
    async def connect_to_websocket(self, url):
        """Connect to the WebSocket server and handle reconnection"""
        while True:
            try:
                async with websockets.connect(url) as websocket:
                    self.websocket = websocket
                    logging.info(f"Connected to WebSocket server at {url}")
                    
                    # Set the websocket in the log manager for real-time log streaming
                    self.log_manager.set_websocket(websocket)
                    
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
                            self.sensor_manager.robot_state = RobotState.STANDBY
                            
                            # Update sensor manager about client disconnect
                            # self.sensor_manager.update_client_status(False, True)
                            self.sensor_manager.robot_state.setConnected(False)
                            break
            except Exception as e:
                logging.error(f"WebSocket connection error: {e}")
                self.websocket = None
                self.sensor_manager.robot_state = RobotState.STANDBY
                
                # Update sensor manager about client disconnect
                # self.sensor_manager.update_client_status(False, True)
                self.sensor_manager.robot_state.setConnected(False)
                
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
                # Handle welcome message from server (not a client connection)
                logging.info(f"Received welcome message from server, server assigned ID: {data['data']['clientId']}")
                
                # This is just the server's welcome, not a client connecting to us
                # We should NOT stop IP announcements here or set client_connected
                
                # After receiving welcome from server, register as a car
                # await self.register_as_car()
            
            elif data["name"] == "client_register":
                # Only set client_connected when a controller connects to the server
                if data["data"].get("type") == "controller":
                    logging.info(f"Received client register message from controller, client ID: {data['data'].get('id', 'unknown')}")
                    
                    self.sensor_manager.robot_state.setConnected(True)
                    # if self.sensor_manager.robot_state == RobotState.MANUAL_CONTROL:
                    #     self.sensor_manager.robot_state = RobotState.STANDBY
                    #     self.sensor_manager.register_client_connection()

                    # Apply the right mode based on the settings
                            # Apply special modes
                    settings = self.config_manager.get()
                    self.sensor_manager.set_tracking(settings["modes"]["tracking_enabled"])
                    self.sensor_manager.set_circuit_mode(settings["modes"]["circuit_mode_enabled"])
                    self.sensor_manager.set_normal_mode(settings["modes"]["normal_mode_enabled"])

                    if settings["modes"]["tracking_enabled"]:
                        self.aicamera_manager.start_face_following()
                    else:
                        self.aicamera_manager.stop_face_following()
                    
                    if settings["modes"]["circuit_mode_enabled"]:
                        self.aicamera_manager.start_color_control()
                        self.aicamera_manager.start_traffic_sign_detection()
                    else:
                        self.aicamera_manager.stop_color_control()
                        self.aicamera_manager.stop_traffic_sign_detection()

                    self.last_activity_time = time.time()
                      # Update sensor manager about client connection
                    # self.sensor_manager.update_client_status(False, True)
                    
                    # Now that a controller is connected, clear IP announcement queue
                    # but keep the task running to detect network changes
                    self.tts_manager.clear_queue(min_priority=1)
                    await self.tts_manager.stop_speech()
                    
                    # Note: We're not cancelling self.ip_speaking_task anymore
                    # so it keeps monitoring for IP address changes
                    
                    # Send initial data
                    await self.send_sensor_data_to_client()
                    await self.send_camera_status_to_client()
                else:
                    logging.info(f"Received client register message, type: {data['data'].get('type', 'unknown')}")

            elif data["name"] == "client_disconnected":
                # Handle client disconnect notification
                logging.info(f"Received client disconnect notification, client ID: {data['data'].get('id', 'unknown')}")
                
                # Update sensor manager about client disconnect
                self.sensor_manager.robot_state = RobotState.STANDBY
                self.sensor_manager.robot_state.setConnected(False)
                
                # Update sensor manager about client disconnect
                # self.sensor_manager.update_client_status(False, True)
                

            elif data["name"] == "gamepad_input":
                # Check if robot is in GPT controlled state - completely ignore input if it is
                if self.sensor_manager.robot_state == RobotState.GPT_CONTROLLED or self.sensor_manager.robot_state == RobotState.TRACKING_MODE or self.sensor_manager.robot_state == RobotState.DEMO_MODE or self.sensor_manager.robot_state == RobotState.CIRCUIT_MODE:
                    logging.info("Completely ignoring gamepad input while in GPT controlled state")
                    return
                    
                # Handle gamepad input
                await self.handle_gamepad_input(data["data"])
                
                # Update client activity time for safety monitoring
                self.sensor_manager.register_client_input()
                self.last_activity_time = time.time()
                
                # Ensure client is marked as connected when we receive input
                if self.sensor_manager.robot_state != RobotState.MANUAL_CONTROL and self.sensor_manager.robot_state != RobotState.EMERGENCY_CONTROL:
                    logging.info("Received gamepad input from client, marking as connected")
                    self.sensor_manager.robot_state = RobotState.MANUAL_CONTROL
            
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
                logging.info(f'Received settings update request: {data["data"]}')
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
                    language = data["data"].get("language", "en")
                    logging.info(f"Received TTS request: {text} in {language}")
                    await self.tts_manager.say(text, lang=language, priority=1)
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
            
            elif data["name"] == "stop_sound":
                # Handle stop sound request
                logging.info("Received stop sound request")
                self.sound_manager.stop_sound()
                await self.send_command_response({
                    "success": True,
                    "message": "All sounds stopped"
                })
                
            elif data["name"] == "stop_tts":
                # Handle stop TTS request
                logging.info("Received stop TTS request")
                success = await self.tts_manager.stop_speech()
                await self.send_command_response({
                    "success": success,
                    "message": "TTS speech stopped"
                })            
            
            elif data["name"] == "gpt_command":
                # Handle GPT command
                prompt = data["data"].get("prompt", "")
                use_camera = data["data"].get("useCamera", False)
                use_ai_voice = data["data"].get("useAiVoice", False)
                conversation_mode = data["data"].get("conversationMode", False)
                
                logging.info(f"Received GPT command: prompt='{prompt}', useCamera={use_camera}, useAiVoice={use_ai_voice}, conversationMode={conversation_mode}")

                old_state = self.sensor_manager.robot_state
                # stop aicamera_manager ai features
                self.aicamera_manager.stop_face_following()
                self.aicamera_manager.stop_color_control()
                self.aicamera_manager.stop_traffic_sign_detection()

                # Set robot state to GPT controlled
                self.sensor_manager.robot_state = RobotState.GPT_CONTROLLED
                
                # Send sensor data update immediately to update client UI with GPT_CONTROLLED state
                await self.send_sensor_data_to_client()
                
                # Process GPT command in a separate task to avoid blocking the WebSocket message handler
                asyncio.create_task(self._handle_gpt_command(prompt, use_camera, use_ai_voice, conversation_mode))
                    

            elif data["name"] == "cancel_gpt":
                # Handle cancel GPT command
                conversation_mode = data["data"].get("conversationMode", False)
                logging.info("Received cancel GPT command")
                success = await self.gpt_manager.cancel_gpt_command(websocket=self.websocket, conversation_mode=conversation_mode)
                await self.send_command_response({
                    "success": success,
                    "message": "GPT command cancelled"
                })

            elif data["name"] == "create_thread":
                # Handle create thread command
                logging.info("Received create thread command")
                success = await self.gpt_manager.create_new_conversation(self.websocket)
                await self.send_command_response({
                        "success": success,
                        "message": "Thread created successfully"
                })                
                 
            elif data["name"] == "network_scan":
                # Handle network scan request
                logging.info("Received network scan request")
                networks = await self.network_manager.scan_wifi_networks()
                await self.send_network_list(networks)
            
            elif data["name"] == "network_update":
                # Handle network update request
                if "action" in data["data"] and "data" in data["data"]:
                    action = data["data"]["action"]
                    network_data = data["data"]["data"]
                    logging.info(f"Received network update request: {action}")
                    
                    result = await self.execute_network_action(action, network_data)
                    await self.send_command_response(result)
                    
                    # After network update, send updated network list
                    if result["success"]:
                        networks = await self.network_manager.scan_wifi_networks()
                        await self.send_network_list(networks)
            
            elif data["name"] == "reset_settings":
                # Handle reset settings request
                logging.info("Received reset settings request")
                section = data["data"].get("section")
                success = self.config_manager.reset_to_defaults(section)
                
                # Apply the reset settings
                await self.apply_config_settings()
                
                # Send response
                await self.send_command_response({
                    "success": success,
                    "message": f"Settings reset to defaults{' for section: ' + section if section else ''}"
                })
                
                # Send updated settings to client
                await self.send_settings_to_client()
                
                # Announce via TTS
                await self.tts_manager.say(f"Settings reset to defaults{' for ' + section if section else ''}", priority=1)

            elif data["name"] == "start_listening":
                # Handle start listening request
                logging.info("Received start listening request")
                await self.audio_manager.start_recording(self.websocket)
                await self.send_command_response({
                    "success": True,
                    "message": "Started listening"
                })

            elif data["name"] == "stop_listening":
                # Handle stop listening request
                logging.info("Received stop listening request")
                await self.audio_manager.stop_recording()
                await self.send_command_response({
                    "success": True,
                    "message": "Stopped listening"
                })

            elif data["name"] == "audio_stream":
                audio_base64 = data["data"].get("audio")
                if audio_base64:
                    try:
                        import base64, tempfile, os
                        
                        # Remove "data:audio/wav;base64," header if present
                        if audio_base64.startswith("data:"):
                            header, encoded = audio_base64.split(",", 1)
                        else:
                            encoded = audio_base64
                        
                        # Decode from base64
                        audio_bytes = base64.b64decode(encoded)
                        
                        # Save to a temporary WAV file
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_wav:
                            temp_wav.write(audio_bytes)
                            wav_path = temp_wav.name
                        
                        logging.info(f"Received WAV audio chunk -> {wav_path}")
                        
                        # Play the audio file - each chunk should now be a complete WAV
                        self.sound_manager.play_voice_stream(wav_path)
                        
                        # Schedule cleanup of temporary file after a delay
                        def cleanup_temp_file(path, delay=5):
                            import time
                            time.sleep(delay)
                            try:
                                if os.path.exists(path):
                                    os.unlink(path)
                                    logging.debug(f"Cleaned up temporary audio file: {path}")
                            except Exception as e:
                                logging.error(f"Error cleaning up temp file {path}: {e}")
                                
                        threading.Thread(target=cleanup_temp_file, args=(wav_path,), daemon=True).start()
                        
                    except Exception as e:
                        logging.error(f"Error processing audio_stream (WAV): {e}")
            else:
                logging.info(f"Received message of type: {data['name']}")
            
        except json.JSONDecodeError:
            logging.warning(f"Received non-JSON message: {message}")
        except Exception as e:
            logging.error(f"Error processing message: {e}")
    
    async def execute_network_action(self, action, data):
        """Execute network-related actions"""
        result = {"success": False, "message": "Unknown network action"}
        
        try:
            if action == "connect_wifi":
                if "ssid" in data and "password" in data:
                    result = await self.network_manager.connect_to_wifi(
                        data["ssid"], data["password"]
                    )
                    
                    # If successful, update the TTS
                    if result["success"]:
                        await self.tts_manager.say(f"Connected to WiFi network {data['ssid']}", priority=1)
                else:
                    result = {"success": False, "message": "Missing SSID or password"}
            
            elif action == "add_network":
                if "ssid" in data and "password" in data:
                    result = await self.network_manager.add_or_update_wifi(
                        data["ssid"], data["password"]
                    )
                    
                    if result["success"]:
                        await self.tts_manager.say(f"Saved WiFi network {data['ssid']}", priority=1)
                else:
                    result = {"success": False, "message": "Missing SSID or password"}
            
            elif action == "remove_network":
                if "ssid" in data:
                    result = await self.network_manager.remove_wifi_network(data["ssid"])
                    
                    if result["success"]:
                        await self.tts_manager.say(f"Removed WiFi network {data['ssid']}", priority=1)
                else:
                    result = {"success": False, "message": "Missing SSID"}
            
            elif action == "update_ap_settings":
                ssid = data.get("ap_name")
                password = data.get("ap_password")
                
                if ssid or password:
                    result = await self.network_manager.update_ap_settings(ssid, password)
                    
                    if result["success"]:
                        await self.tts_manager.say("Access point settings updated", priority=1)
                else:
                    result = {"success": False, "message": "No settings provided"}
            
            elif action == "create_ap":
                # Switch to AP mode
                success = await self.network_manager.switch_wifi_mode("ap")
                
                if success:
                    result = {
                        "success": True,
                        "message": "Switched to Access Point mode"
                    }
                    await self.tts_manager.say("Switched to Access Point mode", priority=1)
                else:
                    result = {
                        "success": False,
                        "message": "Failed to switch to Access Point mode"
                    }
            
            elif action == "connect_wifi_mode":
                # Switch to WiFi client mode
                success = await self.network_manager.switch_wifi_mode("wifi")
                
                if success:
                    result = {
                        "success": True,
                        "message": "Switched to WiFi client mode"
                    }
                    await self.tts_manager.say("Switched to WiFi client mode", priority=1)
                else:
                    result = {
                        "success": False,
                        "message": "Failed to switch to WiFi client mode"
                    }
            
            else:
                result = {
                    "success": False,
                    "message": f"Unknown network action: {action}"
                }
                
        except Exception as e:
            logging.error(f"Error executing network action {action}: {e}")
            result = {
                "success": False,
                "message": f"Error: {str(e)}"
            }
            
        return result
    
    async def send_network_list(self, networks):
        """Send list of available WiFi networks to client"""
        if self.websocket:
            try:
                # Freeze robot state while sending network list
                self.sensor_manager.robot_state = RobotState.STANDBY
                # Get current connection status first for more complete information
                connection_status = await self.network_manager.get_connection_status()
                
                # Get current connection if available
                current_connection = None
                if "current_connection" in connection_status and "ssid" in connection_status["current_connection"]:
                    current_connection = connection_status["current_connection"]
                
                # Get saved networks
                saved_networks = connection_status.get("saved_networks", [])
                
                # Create extended network data by marking networks that are saved
                network_data = {
                    "networks": networks,
                    "saved_networks": saved_networks,
                    "status": {
                        "ap_mode_active": connection_status["ap_mode_active"],
                        "current_ip": connection_status["ip_addresses"].get(self.network_manager.wifi_interface, "Unknown"),
                        "current_connection": current_connection,
                        "ap_ssid": connection_status.get("ap_ssid", "ByteRacer_AP"),
                        "internet_connected": connection_status.get("internet_connected", False)
                    }
                }
                
                await self.websocket.send(json.dumps({
                    "name": "network_list",
                    "data": network_data,
                    "createdAt": int(time.time() * 1000)
                }))
                logging.debug(f"Sent network list with {len(networks)} networks")
            except Exception as e:
                logging.error(f"Error sending network list: {e}")
    
    async def handle_gamepad_input(self, data):
        """Handle gamepad input data"""
        # Check if robot is in GPT controlled state - ignore input if it is
        if self.sensor_manager.robot_state == RobotState.GPT_CONTROLLED:
            logging.info("Ignoring gamepad input while in GPT controlled state")
            return
            
        # Extract values from gamepad data
        turn_value = float(data.get("turn", 0))
        speed_value = float(data.get("speed", 0))
        camera_pan_value = float(data.get("turnCameraX", 0))
        camera_tilt_value = float(data.get("turnCameraY", 0))
        use_button = data.get("use", False)
        
        # Get acceleration_factor from config (between 0.1 and 1.0)
        acceleration_factor = self.config_manager.get("drive.acceleration_factor")
        
        # Ensure acceleration_factor is within valid range
        acceleration_factor = max(0.1, min(1.0, acceleration_factor))
        
        # Calculate acceleration for sound effects
        now = time.time()
        dt = now - self.last_motion_update
        if dt > 0:
            # Calculate raw acceleration
            raw_acceleration = (speed_value - self.last_speed) / dt
            
            # Only apply acceleration limit if factor is less than 1.0
            if acceleration_factor < 1.0:
                # Scale max acceleration inversely - smaller factor = tighter limit
                # When factor is 1.0, there should be no limit (infinite acceleration allowed)
                # When factor is close to 0, the limit should be very restrictive
                max_acceleration = 2.0 / (1.1 - acceleration_factor)  # This creates a curve that approaches infinity as factor approaches 1.0
                
                if abs(raw_acceleration) > max_acceleration:
                    # Limit acceleration to the maximum allowed value
                    acceleration = max_acceleration if raw_acceleration > 0 else -max_acceleration
                    
                    # Adjust speed value to respect acceleration limit
                    speed_value = self.last_speed + (acceleration * dt)
                else:
                    acceleration = raw_acceleration
            else:
                # No acceleration limit when factor is at maximum
                acceleration = raw_acceleration
        else:
            acceleration = 0
        
        self.last_speed = speed_value
        self.last_turn = turn_value
        self.last_acceleration = acceleration
        self.last_motion_update = now
        
        # Pass inputs through sensor manager to handle safety overrides
        speed_value, turn_value, emergency = self.sensor_manager.update_motion(speed_value, turn_value)

        # Set camera angles - always allow camera control even during emergencies
        self.px.set_cam_pan_angle(camera_pan_value * 90)
        
        # Handle camera tilt with different ranges for up/down
        if camera_tilt_value >= 0:
            self.px.set_cam_tilt_angle(camera_tilt_value * 65)
        else:
            self.px.set_cam_tilt_angle(camera_tilt_value * 35)
        
        # Set motor speeds with safety constraints applied
        # Convert percentage values (0-100) to actual values
        max_speed_pct = self.config_manager.get("drive.max_speed")
        max_turn_pct = self.config_manager.get("drive.max_turn_angle")
        
        # Ensure values are within valid range (0-100%)
        max_speed_pct = max(0, min(100, max_speed_pct))
        max_turn_pct = max(0, min(100, max_turn_pct))
        
        # Convert percentages to actual values
        max_speed = max_speed_pct / 100.0    # Convert to 0.0-1.0 range
        max_turn = max_turn_pct / 100.0 * 30  # Convert to degrees (assuming 45° is max possible turn)
        
        enhanced_turning = self.config_manager.get("drive.enhanced_turning")
        turn_in_place = self.config_manager.get("drive.turn_in_place")
        
        # Apply motor commands based on drive settings
        abs_turn = abs(turn_value)
        abs_speed = abs(speed_value)
        turn_direction = 1 if turn_value > 0 else -1 if turn_value < 0 else 0
        
        # Check if we should do in-place rotation (when there's turning but no forward/backward motion)
        if turn_in_place and abs_turn > 0.1 and abs_speed < 0.1:
            # Turn in place by driving wheels in opposite directions
            turning_power = turn_value * max_speed
            self.px.set_motor_speed(1, turning_power * 100)        # Left motor
            self.px.set_motor_speed(2, turning_power * 100)        # Right motor (same direction - reversed in hardware)
            self.px.set_dir_servo_angle(0)                   # Center the steering
        
        # Otherwise use differential steering if enabled or regular steering if not
        else:
            if enhanced_turning and abs_turn > 0.1:
                # Differential steering: Reduce speed of inner wheel based on turn amount
                turn_factor = abs_turn * 0.9  # How much to reduce inner wheel speed (max 90% reduction)
                
                # Calculate per-wheel speeds
                if turn_direction > 0:  # Turning right
                    left_speed = speed_value  # Outer wheel at full speed
                    right_speed = speed_value * (1 - turn_factor)  # Inner wheel slowed
                else:  # Turning left or straight
                    left_speed = speed_value * (1 - (turn_factor if turn_direction < 0 else 0))  # Inner wheel slowed if turning left
                    right_speed = speed_value  # Outer wheel at full speed
                
                # Apply speeds to motors
                self.px.set_motor_speed(1, left_speed * max_speed * 100)    # Left motor
                self.px.set_motor_speed(2, -right_speed * max_speed * 100)  # Right motor (reversed in hardware)
                self.px.set_dir_servo_angle(turn_value * max_turn)    # Still use steering for sharper turns
            else:
                # Regular steering (no differential)
                self.px.set_motor_speed(1, speed_value * max_speed * 100)   # Left motor at full speed
                self.px.set_motor_speed(2, speed_value * -max_speed * 100)  # Right motor at full speed (reversed)
                self.px.set_dir_servo_angle(turn_value * max_turn)    # Use steering only

                # Update driving sounds
        self.sound_manager.update_driving_sounds(speed_value, turn_value, acceleration)
    
    async def handle_emergency(self, emergency):
        """Handle emergency situations"""
        logging.warning(f"Emergency callback triggered: {emergency.name}")

        # Clear TTS queue and stop any ongoing speech
        self.tts_manager.clear_queue()
        await self.tts_manager.stop_speech()  # Fixed: properly await the async call

        # Provide feedback via TTS - make sure to properly await the async call
        if emergency == EmergencyState.COLLISION_FRONT:
            await self.tts_manager.say("Emergency. Obstacle detected ahead. Maintaining safe distance.", priority=2)
        elif emergency == EmergencyState.EDGE_DETECTED:
            await self.tts_manager.say("Emergency. Edge detected. Backing up.", priority=2)
        elif emergency == EmergencyState.CLIENT_DISCONNECTED:
            await self.tts_manager.say("Emergency stop. Client disconnected.", priority=2)
        elif emergency == EmergencyState.LOW_BATTERY:
            await self.tts_manager.say(f"Warning. Battery level low. Please recharge soon.", priority=2)
        elif emergency == EmergencyState.MANUAL_STOP:
            await self.tts_manager.say("Emergency stop activated.", priority=2)

        # Play alert sound immediately
        self.sound_manager.play_alert("emergency")
        
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
        if "modes" in settings:
            modes = settings["modes"]
            if "tracking_enabled" in modes:
                self.config_manager.set("modes.tracking_enabled", modes["tracking_enabled"])
                self.sensor_manager.set_tracking(modes["tracking_enabled"])
                if modes["tracking_enabled"]:
                    self.sensor_manager.robot_state = RobotState.TRACKING_MODE
                    self.aicamera_manager.start_face_following()
                else:   
                    self.aicamera_manager.stop_face_following()
            
            if "circuit_mode_enabled" in modes:
                self.config_manager.set("modes.circuit_mode_enabled", modes["circuit_mode_enabled"])
                self.sensor_manager.set_circuit_mode(modes["circuit_mode_enabled"])
                
                if modes["circuit_mode_enabled"]:
                    self.sensor_manager.robot_state = RobotState.CIRCUIT_MODE
                    self.aicamera_manager.start_color_control()
                    self.aicamera_manager.start_traffic_sign_detection()
                else:   
                    self.aicamera_manager.stop_color_control()
                    self.aicamera_manager.stop_traffic_sign_detection()

            if "demo_mode_enabled" in modes:
                self.config_manager.set("modes.demo_mode_enabled", modes["demo_mode_enabled"])
                self.sensor_manager.set_demo_mode(modes["demo_mode_enabled"])
                if modes["demo_mode_enabled"]:
                    self.sensor_manager.robot_state = RobotState.DEMO_MODE

            if "normal_mode_enabled" in modes:
                self.config_manager.set("modes.normal_mode_enabled", modes["normal_mode_enabled"])
                self.sensor_manager.set_normal_mode(modes["normal_mode_enabled"])
                if modes["normal_mode_enabled"]:
                    self.sensor_manager.robot_state = RobotState.STANDBY
        if "sound" in settings:
            sound = settings["sound"]
            if "enabled" in sound:
                self.config_manager.set("sound.enabled", sound["enabled"])
                self.sound_manager.set_enabled(sound["enabled"])
            
            if "volume" in sound:
                self.config_manager.set("sound.volume", sound["volume"])
                self.sound_manager.set_volume(sound["volume"])

            if "sound_volume" in sound:
                self.config_manager.set("sound.sound_volume", sound["sound_volume"])
                self.sound_manager.set_sound_volume(sound["sound_volume"])
            
            if "tts_enabled" in sound:
                self.config_manager.set("sound.tts_enabled", sound["tts_enabled"])
                self.tts_manager.set_enabled(sound["tts_enabled"])

            if "tts_volume" in sound:
                self.config_manager.set("sound.tts_volume", sound["tts_volume"])
                self.tts_manager.set_volume(sound["tts_volume"])
            
            if "tts_language" in sound:
                self.config_manager.set("sound.tts_language", sound["tts_language"])
                self.tts_manager.set_language(sound["tts_language"])

            if "driving_volume" in sound:
                self.config_manager.set("sound.driving_volume", sound["driving_volume"])
                self.sound_manager.set_category_volume("driving", sound["driving_volume"])

            if "alert_volume" in sound:
                self.config_manager.set("sound.alert_volume", sound["alert_volume"])
                self.sound_manager.set_category_volume("alert", sound["alert_volume"])
            
            if "custom_volume" in sound:
                self.config_manager.set("sound.custom_volume", sound["custom_volume"])
                self.sound_manager.set_category_volume("custom", sound["custom_volume"])
                
            if "voice_volume" in sound:
                self.config_manager.set("sound.voice_volume", sound["voice_volume"])
                self.sound_manager.set_category_volume("voice", sound["voice_volume"])

            if "user_tts_volume" in sound:
                self.config_manager.set("sound.user_tts_volume", sound["user_tts_volume"])
                self.tts_manager.set_user_tts_volume(sound["user_tts_volume"])

            if "tts_audio_gain" in sound:
                self.config_manager.set("sound.tts_audio_gain", sound["tts_audio_gain"])
                self.tts_manager.set_tts_audio_gain(sound["tts_audio_gain"])
            
            if "system_tts_volume" in sound:
                self.config_manager.set("sound.system_tts_volume", sound["system_tts_volume"])
                self.tts_manager.set_system_tts_volume(sound["system_tts_volume"])

            if "emergency_tts_volume" in sound:
                self.config_manager.set("sound.emergency_tts_volume", sound["emergency_tts_volume"])
                self.tts_manager.set_emergency_tts_volume(sound["emergency_tts_volume"])
        
        if "safety" in settings:
            safety = settings["safety"]
            if "collision_avoidance" in safety:
                self.config_manager.set("safety.collision_avoidance", safety["collision_avoidance"])
                self.sensor_manager.set_collision_avoidance(safety["collision_avoidance"])

            if "collision_threshold" in safety:
                self.config_manager.set("safety.collision_threshold", safety["collision_threshold"])
                self.sensor_manager.collision_threshold = safety["collision_threshold"]
            
            if "edge_detection" in safety:
                self.config_manager.set("safety.edge_detection", safety["edge_detection"])
                self.sensor_manager.set_edge_detection(safety["edge_detection"])

            if "edge_threshold" in safety:
                self.config_manager.set("safety.edge_threshold", safety["edge_threshold"])
                self.sensor_manager.set_edge_detection_threshold(safety["edge_threshold"])
            
            if "auto_stop" in safety:
                self.config_manager.set("safety.auto_stop", safety["auto_stop"])
                self.sensor_manager.set_auto_stop(safety["auto_stop"])

            if "client_timeout" in safety:
                self.config_manager.set("safety.client_timeout", safety["client_timeout"])
                self.sensor_manager.client_timeout = safety["client_timeout"]

        if "drive" in settings:
            drive = settings["drive"]
            if "max_speed" in drive:
                self.config_manager.set("drive.max_speed", drive["max_speed"])
            
            if "max_turn_angle" in drive:
                self.config_manager.set("drive.max_turn_angle", drive["max_turn_angle"])

            if "acceleration_factor" in drive:
                self.config_manager.set("drive.acceleration_factor", drive["acceleration_factor"])

            if "enhanced_turning" in drive:
                self.config_manager.set("drive.enhanced_turning", drive["enhanced_turning"])
            
            if "turn_in_place" in drive:
                self.config_manager.set("drive.turn_in_place", drive["turn_in_place"])

        if "github" in settings:
            if "branch" in settings["github"]:
                self.config_manager.set("github.branch", settings["github"]["branch"])
            if "repo_url" in settings["github"]:
                self.config_manager.set("github.repo_url", settings["github"]["repo_url"])
            if "auto_update" in settings["github"]:
                self.config_manager.set("github.auto_update", settings["github"]["auto_update"])
                
        if "api" in settings:
            api = settings["api"]
            
            if "openai_api_key" in api:
                self.config_manager.set("api.openai_api_key", api["openai_api_key"])
                # Update GPT manager with new API key if it exists
                if hasattr(self, 'gpt_manager'):
                    self.gpt_manager.api_key = api["openai_api_key"]
                    logging.info("Updated GPT manager with new API key")

        if "camera" in settings:
            camera = settings["camera"]
            
            # First collect all camera setting changes
            camera_changes = {}
            
            if "vflip" in camera:
                self.config_manager.set("camera.vflip", camera["vflip"])
                camera_changes['vflip'] = camera["vflip"]
            
            if "hflip" in camera:
                self.config_manager.set("camera.hflip", camera["hflip"])
                camera_changes['hflip'] = camera["hflip"]

            if "local_display" in camera:
                self.config_manager.set("camera.local_display", camera["local_display"])
                camera_changes['local'] = camera["local_display"]

            if "web_display" in camera:
                self.config_manager.set("camera.web_display", camera["web_display"])
                camera_changes['web'] = camera["web_display"]

            if "camera_size" in camera:
                self.config_manager.set("camera.camera_size", camera["camera_size"])
                camera_changes['camera_size'] = camera["camera_size"]
            
            # Only update and restart if there are actual changes
            if camera_changes:
                restart_needed = self.camera_manager.update_settings(**camera_changes)
                if restart_needed:
                    await self.camera_manager.restart()        
        
        # Save settings
        await self.save_config_settings()
        await self.send_settings_to_client()
    
    async def execute_robot_command(self, command):
        """Handle system commands and provide feedback"""
        result = {"success": False, "message": "Unknown command"}
        
        try:
            if command == "restart_robot":
                # Restart the entire system
                await self.tts_manager.say("Restarting system. Please wait.", priority=1, blocking=True)
                result = {"success": True, "message": "Rebooting system..."}
                # Schedule system reboot after response is sent
                threading.Timer(2.0, lambda: subprocess.run("sudo reboot", shell=True)).start()
                
            elif command == "stop_robot":
                # Shutdown the system
                await self.tts_manager.say("Shutting down system. Goodbye!", priority=1, blocking=True)
                result = {"success": True, "message": "Shutting down system..."}
                threading.Timer(2.0, lambda: subprocess.run("sudo shutdown -h now", shell=True)).start()
                
            elif command == "restart_all_services":

                result["success"] = True
                result["message"] = "All services restarted"
                # Restart all three services
                subprocess.Popen(
                    ["bash", f"{PROJECT_DIR}/byteracer/scripts/restart_services.sh"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                
            elif command == "restart_websocket":
                # Restart just the WebSocket service
                success = subprocess.run(
                    f"cd {PROJECT_DIR} && sudo bash ./byteracer/scripts/restart_websocket.sh",
                    shell=True,
                    check=False
                ).returncode == 0
                
                result["success"] = success
                result["message"] = "WebSocket service restarted" if success else "Failed to restart WebSocket service"
                
            elif command == "restart_web_server":
                # Restart just the web server
                success = subprocess.run(
                    f"cd {PROJECT_DIR} && sudo bash ./byteracer/scripts/restart_web_server.sh",
                    shell=True,
                    check=False
                ).returncode == 0
                
                result["success"] = success
                result["message"] = "Web server restarted" if success else "Failed to restart web server"
                
            elif command == "restart_python_service":
                # Restart just the Python service

                result["success"] = True
                result["message"] = "Python service will restart"
                
                # Run restart_python.sh in a new session so it stays alive
                subprocess.Popen(
                    ["bash", f"{PROJECT_DIR}/byteracer/scripts/restart_python.sh"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                
            elif command == "restart_camera_feed":
                # Restart camera feed
                await self.tts_manager.say("Restarting camera feed.", priority=1)
                success = await self.camera_manager.restart()
                
                result["success"] = success
                result["message"] = "Camera feed restarted" if success else "Failed to restart camera feed"
                
            elif command == "check_for_updates":
                # Check for updates
                
                result["success"] = True
                result["message"] = "Update check completed"

                subprocess.Popen(
                    ["bash", f"{PROJECT_DIR}/byteracer/scripts/update.sh"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                
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
        if self.websocket:
            try:
                # Get raw sensor data
                sensor_data = self.sensor_manager.get_sensor_data()
                
                # Get system resource data
                cpu_usage = psutil.cpu_percent()
                ram = psutil.virtual_memory()
                ram_usage = ram.percent
                
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
                    "isDemoModeActive": sensor_data["settings"]["demo_mode"],
                    "isNormalModeActive": sensor_data["settings"]["normal_mode"],
                    "isGptModeActive": sensor_data["settings"]["gpt_mode"],
                    "clientConnected": self.sensor_manager.robot_state == RobotState.MANUAL_CONTROL,
                    "lastClientActivity": int(self.last_activity_time * 1000),  # Convert to milliseconds
                    "speed": sensor_data["speed"],  # Add speed value
                    "turn": sensor_data["turn"],    # Add turn value
                    "acceleration": sensor_data["acceleration"],  # Add acceleration value
                    "cpuUsage": cpu_usage,  # Add CPU usage
                    "ramUsage": ram_usage   # Add RAM usage
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
        if self.websocket:
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
        if self.websocket:
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
        if self.websocket:
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
        while True:
            try:
                # Always update sensor manager with current client status
                # self.sensor_manager.update_client_status(
                #     self.sensor_manager.robot_state == RobotState.MANUAL_CONTROL,
                #     self.sensor_manager.robot_state != RobotState.STANDBY
                # )
                
                # Send sensor data every second if client is connected

                try:
                    await self.send_sensor_data_to_client()
                    logging.debug("Periodic sensor data sent")
                except Exception as e:
                    logging.error(f"Error sending periodic sensor data: {e}")

                
                # Always use a consistent update interval, don't slow down when idle
                # This ensures continuous data flow
                await asyncio.sleep(0.1)
                
            except asyncio.CancelledError:
                logging.info("Periodic tasks cancelled")
                break
            except Exception as e:
                logging.error(f"Error in periodic tasks: {e}", exc_info=True)
                await asyncio.sleep(2)  # Shorter sleep on error

    async def _handle_gpt_command(self, prompt, use_camera, use_ai_voice, conversation_mode):
        """
        Handle GPT command processing in a separate task so it doesn't block the WebSocket message handler.
        This allows the robot to properly ignore input during GPT mode instead of queuing them.
        
        Args:
            prompt: The user's prompt text
            use_camera: Whether to use the camera
            use_ai_voice: Whether to use AI voice for TTS
            conversation_mode: Whether to use conversation mode
        """
        try:
            # Process the GPT command
            success = await self.gpt_manager.process_gpt_command(prompt, use_camera, 
                                                                websocket=self.websocket,
                                                                use_ai_voice=use_ai_voice,
                                                                conversation_mode=conversation_mode)
            
            logging.info(f"GPT command processing completed with status: {success}")
            
            # Send updated sensor data to client to reflect state changes
            await self.send_sensor_data_to_client()
            
        except Exception as e:
            logging.error(f"Error processing GPT command: {e}")
            await self.send_sensor_data_to_client()

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
