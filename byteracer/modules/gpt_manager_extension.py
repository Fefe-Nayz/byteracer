"""
GPT Manager extension helper methods for better script organization.
Contains implementation of predefined functions and other helper methods.
"""

import logging
import asyncio
import time
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

async def execute_predefined_function(self, function_name: str, parameters: Dict[str, Any]) -> bool:
    """
    Execute a predefined function with proper parameter validation.
    
    Args:
        function_name: The name of the function to execute
        parameters: Dictionary of parameters for the function
        
    Returns:
        bool: Success status
    """
    try:
        # MOVEMENT FUNCTIONS
        if function_name == "move":
            # Validate parameters
            if "speed" not in parameters or "motor_id" not in parameters:
                logger.warning(f"Missing required parameters for move function. Need speed and motor_id.")
                return False
                
            speed = parameters.get("speed", 0)
            motor_id = parameters.get("motor_id", "")
            
            # Validate values
            if not isinstance(speed, (int, float)) or not -100 <= speed <= 100:
                logger.warning(f"Invalid speed value for move: {speed}. Must be between -100 and 100.")
                speed = max(min(speed, 100), -100)  # Clamp to valid range
                
            if motor_id not in ["rear_left", "rear_right"]:
                logger.warning(f"Invalid motor_id: {motor_id}. Must be rear_left or rear_right.")
                return False
                
            # Execute
            if motor_id == "rear_left":
                self.px.set_motor_speed(1, speed)
            elif motor_id == "rear_right":
                self.px.set_motor_speed(2, speed)
                
            logger.info(f"Move {motor_id} at speed {speed}")
            return True
            
        elif function_name == "move_forward":
            speed = parameters.get("speed", 50)
            
            # Validate
            if not isinstance(speed, (int, float)) or not 0 <= speed <= 100:
                logger.warning(f"Invalid forward speed: {speed}. Must be between 0 and 100.")
                speed = max(min(speed, 100), 0)  # Clamp to valid range
                
            # Execute
            self.px.forward(speed)
            logger.info(f"Move forward at speed {speed}")
            return True
            
        elif function_name == "move_backward":
            speed = parameters.get("speed", 50)
            
            # Validate
            if not isinstance(speed, (int, float)) or not 0 <= speed <= 100:
                logger.warning(f"Invalid backward speed: {speed}. Must be between 0 and 100.")
                speed = max(min(speed, 100), 0)  # Clamp to valid range
                
            # Execute
            self.px.backward(speed)
            logger.info(f"Move backward at speed {speed}")
            return True
            
        elif function_name == "stop":
            self.px.stop()
            logger.info("Stop all motors")
            return True
            
        elif function_name == "turn":
            angle = parameters.get("angle", 0)
            
            # Validate
            if not isinstance(angle, (int, float)) or not -30 <= angle <= 30:
                logger.warning(f"Invalid turn angle: {angle}. Must be between -30 and 30.")
                angle = max(min(angle, 30), -30)  # Clamp to valid range
                
            # Execute
            self.px.set_dir_servo_angle(angle)
            logger.info(f"Turn to angle {angle}")
            return True
            
        # CAMERA FUNCTIONS
        elif function_name == "set_camera_angle":
            pan = parameters.get("pan", None)
            tilt = parameters.get("tilt", None)
            
            # Validate and set pan angle if provided
            if pan is not None:
                if not isinstance(pan, (int, float)) or not -90 <= pan <= 90:
                    logger.warning(f"Invalid camera pan angle: {pan}. Must be between -90 and 90.")
                    pan = max(min(pan, 90), -90)  # Clamp to valid range
                self.px.set_cam_pan_angle(pan)
                logger.info(f"Set camera pan to {pan}")
                
            # Validate and set tilt angle if provided
            if tilt is not None:
                if not isinstance(tilt, (int, float)) or not -35 <= tilt <= 65:
                    logger.warning(f"Invalid camera tilt angle: {tilt}. Must be between -35 and 65.")
                    tilt = max(min(tilt, 65), -35)  # Clamp to valid range
                self.px.set_cam_tilt_angle(tilt)
                logger.info(f"Set camera tilt to {tilt}")
                
            return pan is not None or tilt is not None
            
        # SENSOR FUNCTIONS
        elif function_name == "get_distance":
            # Get distance measurement
            distance = self.px.get_distance()
            # Report the distance via TTS
            asyncio.create_task(self.tts_manager.say(f"Distance: {distance} centimeters", priority=1))
            logger.info(f"Get distance: {distance} cm")
            return True
            
        elif function_name == "get_sensor_data":
            # Get all sensor readings
            sensor_data = {}
            
            try:
                # Distance sensor
                sensor_data["distance"] = self.px.get_distance()
                
                # Line sensors
                sensor_data["line_sensors"] = self.px.get_line_sensor_value()
                
                # Battery voltage
                if hasattr(self.px, "get_battery_voltage"):
                    sensor_data["battery"] = self.px.get_battery_voltage()
                
                # Other sensors from sensor_manager if available
                if hasattr(self, "sensor_manager"):
                    state_data = self.sensor_manager.get_sensor_data()
                    sensor_data.update(state_data)
                
                # Output a summary via TTS
                summary = f"Distance: {sensor_data.get('distance', 'unknown')} cm"
                asyncio.create_task(self.tts_manager.say(summary, priority=1))
                
                logger.info(f"Sensor data: {sensor_data}")
                return True
            except Exception as e:
                logger.error(f"Error getting sensor data: {e}")
                return False
        
        # SOUND FUNCTIONS
        elif function_name == "play_sound":
            sound_name = parameters.get("sound_name", "")
            
            # Validate
            if not sound_name:
                logger.warning("No sound name provided")
                return False
                
            valid_sounds = [
                "alarm", "aurores", "bruh", "cailloux", "fart", "fave", "get-out", 
                "india", "klaxon", "klaxon-2", "laugh", "lingango", "nope", "ph", 
                "pipe", "rat-dance", "scream", "tralalelo-tralala", "tuile", 
                "vine-boom", "wow", "wtf"
            ]
            
            if sound_name not in valid_sounds:
                logger.warning(f"Unknown sound: {sound_name}")
                # Play anyway, in case it's a new sound that was added
                
            # Execute
            self.sound_manager.play_sound("custom", name=sound_name)
            logger.info(f"Play sound: {sound_name}")
            return True
            
        elif function_name == "say":
            text = parameters.get("text", "")
            language = parameters.get("language", "en-US")
            
            # Validate
            if not text:
                logger.warning("No text provided for TTS")
                return False
                
            valid_languages = ["en-US", "en-GB", "de-DE", "es-ES", "fr-FR", "it-IT"]
            if language not in valid_languages:
                logger.warning(f"Invalid language: {language}. Using en-US instead.")
                language = "en-US"
                
            # Execute
            asyncio.create_task(self.tts_manager.say(text, lang=language))
            logger.info(f"Say: {text} (language: {language})")
            return True
            
        # SOUND SETTINGS FUNCTIONS
        elif function_name == "set_sound_enabled":
            enabled = parameters.get("enabled", True)
            if not isinstance(enabled, bool):
                logger.warning(f"Invalid enabled value: {enabled}. Must be boolean.")
                return False
                
            if hasattr(self.sound_manager, "set_sound_enabled"):
                self.sound_manager.set_sound_enabled(enabled)
                logger.info(f"Set sound enabled: {enabled}")
                return True
            return False
            
        elif function_name == "set_sound_volume":
            volume = parameters.get("volume", 50)
            
            if not isinstance(volume, (int, float)) or not 0 <= volume <= 100:
                logger.warning(f"Invalid volume: {volume}. Must be between 0 and 100.")
                volume = max(min(volume, 100), 0)
                
            if hasattr(self.sound_manager, "set_volume"):
                self.sound_manager.set_volume(volume)
                logger.info(f"Set sound volume: {volume}")
                return True
            return False
            
        elif function_name == "set_sound_effect_volume":
            volume = parameters.get("volume", 50)
            
            if not isinstance(volume, (int, float)) or not 0 <= volume <= 100:
                logger.warning(f"Invalid volume: {volume}. Must be between 0 and 100.")
                volume = max(min(volume, 100), 0)
                
            if hasattr(self.sound_manager, "set_effect_volume"):
                self.sound_manager.set_effect_volume(volume)
                logger.info(f"Set sound effect volume: {volume}")
                return True
            return False
            
        elif function_name == "set_tts_enabled":
            enabled = parameters.get("enabled", True)
            if not isinstance(enabled, bool):
                logger.warning(f"Invalid enabled value: {enabled}. Must be boolean.")
                return False
                
            if hasattr(self.tts_manager, "set_enabled"):
                self.tts_manager.set_enabled(enabled)
                logger.info(f"Set TTS enabled: {enabled}")
                return True
            return False
            
        elif function_name == "set_tts_volume":
            volume = parameters.get("volume", 50)
            
            if not isinstance(volume, (int, float)) or not 0 <= volume <= 100:
                logger.warning(f"Invalid volume: {volume}. Must be between 0 and 100.")
                volume = max(min(volume, 100), 0)
                
            if hasattr(self.tts_manager, "set_volume"):
                self.tts_manager.set_volume(volume)
                logger.info(f"Set TTS volume: {volume}")
                return True
            return False
            
        elif function_name == "set_tts_language":
            language = parameters.get("language", "en-US")
            
            valid_languages = ["en-US", "en-GB", "de-DE", "es-ES", "fr-FR", "it-IT"]
            if language not in valid_languages:
                logger.warning(f"Invalid language: {language}. Must be one of {valid_languages}")
                return False
                
            if hasattr(self.tts_manager, "set_language"):
                self.tts_manager.set_language(language)
                logger.info(f"Set TTS language: {language}")
                return True
            return False
            
        elif function_name == "set_category_volume":
            category = parameters.get("category", "")
            volume = parameters.get("volume", 50)
            
            if not category:
                logger.warning("No category provided")
                return False
                
            valid_categories = ["driving", "alert", "custom", "voice"]
            if category not in valid_categories:
                logger.warning(f"Invalid category: {category}. Must be one of {valid_categories}")
                return False
                
            if not isinstance(volume, (int, float)) or not 0 <= volume <= 100:
                logger.warning(f"Invalid volume: {volume}. Must be between 0 and 100.")
                volume = max(min(volume, 100), 0)
                
            if hasattr(self.sound_manager, "set_category_volume"):
                self.sound_manager.set_category_volume(category, volume)
                logger.info(f"Set {category} volume: {volume}")
                return True
            return False
        
        # SAFETY SETTINGS FUNCTIONS
        elif function_name == "set_collision_avoidance":
            enabled = parameters.get("enabled", True)
            if not isinstance(enabled, bool):
                logger.warning(f"Invalid enabled value: {enabled}. Must be boolean.")
                return False
                
            if hasattr(self, "sensor_manager") and hasattr(self.sensor_manager, "set_collision_avoidance"):
                self.sensor_manager.set_collision_avoidance(enabled)
                logger.info(f"Set collision avoidance: {enabled}")
                return True
            return False
            
        elif function_name == "set_collision_threshold":
            threshold = parameters.get("threshold", 30)
            
            if not isinstance(threshold, (int, float)) or not 10 <= threshold <= 100:
                logger.warning(f"Invalid threshold: {threshold}. Must be between 10 and 100.")
                threshold = max(min(threshold, 100), 10)
                
            if hasattr(self, "sensor_manager") and hasattr(self.sensor_manager, "set_collision_threshold"):
                self.sensor_manager.set_collision_threshold(threshold)
                logger.info(f"Set collision threshold: {threshold}")
                return True
            return False
            
        elif function_name == "set_edge_detection":
            enabled = parameters.get("enabled", True)
            if not isinstance(enabled, bool):
                logger.warning(f"Invalid enabled value: {enabled}. Must be boolean.")
                return False
                
            if hasattr(self, "sensor_manager") and hasattr(self.sensor_manager, "set_edge_detection"):
                self.sensor_manager.set_edge_detection(enabled)
                logger.info(f"Set edge detection: {enabled}")
                return True
            return False
            
        elif function_name == "set_edge_threshold":
            threshold = parameters.get("threshold", 0.5)
            
            if not isinstance(threshold, (int, float)) or not 0.1 <= threshold <= 0.9:
                logger.warning(f"Invalid threshold: {threshold}. Must be between 0.1 and 0.9.")
                threshold = max(min(threshold, 0.9), 0.1)
                
            if hasattr(self, "sensor_manager") and hasattr(self.sensor_manager, "set_edge_threshold"):
                self.sensor_manager.set_edge_threshold(threshold)
                logger.info(f"Set edge threshold: {threshold}")
                return True
            return False

        # DRIVE SETTINGS FUNCTIONS
        elif function_name == "set_max_speed":
            speed = parameters.get("speed", 50)
            
            if not isinstance(speed, (int, float)) or not 0 <= speed <= 100:
                logger.warning(f"Invalid speed: {speed}. Must be between 0 and 100.")
                speed = max(min(speed, 100), 0)
                
            if hasattr(self.px, "set_max_speed"):
                self.px.set_max_speed(speed)
                logger.info(f"Set max speed: {speed}")
                return True
            return False
            
        elif function_name == "set_max_turn_angle":
            angle = parameters.get("angle", 50)
            
            if not isinstance(angle, (int, float)) or not 0 <= angle <= 100:
                logger.warning(f"Invalid angle percentage: {angle}. Must be between 0 and 100.")
                angle = max(min(angle, 100), 0)
                
            if hasattr(self.px, "set_max_turn_angle"):
                self.px.set_max_turn_angle(angle)
                logger.info(f"Set max turn angle: {angle}")
                return True
            return False
            
        # CAMERA SETTINGS FUNCTIONS
        elif function_name == "set_camera_flip":
            vflip = parameters.get("vflip", False)
            hflip = parameters.get("hflip", False)
            
            if not isinstance(vflip, bool) or not isinstance(hflip, bool):
                logger.warning(f"Invalid flip values: vflip={vflip}, hflip={hflip}. Must be boolean.")
                return False
                
            if hasattr(self, "camera_manager") and hasattr(self.camera_manager, "set_flip"):
                self.camera_manager.set_flip(vflip, hflip)
                logger.info(f"Set camera flip: vflip={vflip}, hflip={hflip}")
                return True
            return False
            
        elif function_name == "set_camera_size":
            width = parameters.get("width", 640)
            height = parameters.get("height", 480)
            
            if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
                logger.warning(f"Invalid camera size: width={width}, height={height}. Must be positive integers.")
                return False
                
            if hasattr(self, "camera_manager") and hasattr(self.camera_manager, "set_resolution"):
                self.camera_manager.set_resolution(width, height)
                logger.info(f"Set camera size: width={width}, height={height}")
                return True
            return False

        # SYSTEM FUNCTIONS
        elif function_name == "restart_robot":
            logger.info("Restart robot requested")
            # This would typically call a system service or script
            if hasattr(self, "restart_system"):
                self.restart_system()
                return True
            return False
            
        elif function_name == "shutdown_robot":
            logger.info("Shutdown robot requested")
            # This would typically call a system service or script
            if hasattr(self, "shutdown_system"):
                self.shutdown_system()
                return True
            return False
              # ANIMATIONS/EMOTIONS FUNCTIONS
        elif function_name == "wave_hands":
            try:
                logger.info("Executing wave_hands animation")
                # Import the preset animation function from the preset_actions module
                from modules.gpt.preset_actions import wave_hands
                # Call the preset animation with the px instance
                wave_hands(self.px)
                return True
            except Exception as e:
                logger.error(f"Error in wave_hands: {e}")
                return False
                
        elif function_name == "nod":
            try:
                logger.info("Executing nod animation")
                # Import the preset animation function
                from modules.gpt.preset_actions import nod
                # Call the preset animation
                nod(self.px)
                return True
            except Exception as e:
                logger.error(f"Error in nod: {e}")
                return False
                
        elif function_name == "shake_head":
            try:
                logger.info("Executing shake_head animation")
                # Import the preset animation function
                from modules.gpt.preset_actions import shake_head
                # Call the preset animation
                shake_head(self.px)
                return True
            except Exception as e:
                logger.error(f"Error in shake_head: {e}")
                return False
                
        elif function_name == "act_cute":
            try:
                logger.info("Executing act_cute animation")
                # Play a cute sound first (this is not part of the preset function)
                self.sound_manager.play_sound("custom", name="wow")
                # Import and call the preset animation
                from modules.gpt.preset_actions import act_cute
                act_cute(self.px)
                return True
            except Exception as e:
                logger.error(f"Error in act_cute: {e}")
                return False
                
        elif function_name == "think":
            try:
                logger.info("Executing think animation")
                # Play a thinking sound first (not part of the preset)
                self.sound_manager.play_sound("custom", name="pipe")
                # Import and call the preset animation
                from modules.gpt.preset_actions import think
                think(self.px)
                return True
            except Exception as e:
                logger.error(f"Error in think: {e}")
                return False
                
        elif function_name == "celebrate":
            try:
                logger.info("Executing celebrate animation")
                # Play celebration sound first
                self.sound_manager.play_sound("custom", name="rat-dance")
                # Import and call the preset animation
                from modules.gpt.preset_actions import celebrate
                celebrate(self.px)
                return True
            except Exception as e:
                logger.error(f"Error in celebrate: {e}")
                return False
                
        elif function_name == "resist":
            try:
                logger.info("Executing resist animation")
                # Import and call the preset animation
                from modules.gpt.preset_actions import resist
                resist(self.px)
                return True
            except Exception as e:
                logger.error(f"Error in resist: {e}")
                return False
                
        elif function_name == "twist_body":
            try:
                logger.info("Executing twist_body animation")
                # Import and call the preset animation
                from modules.gpt.preset_actions import twist_body
                twist_body(self.px)
                return True
            except Exception as e:
                logger.error(f"Error in twist_body: {e}")
                return False
                
        elif function_name == "rub_hands":
            try:
                logger.info("Executing rub_hands animation")
                # Import and call the preset animation
                from modules.gpt.preset_actions import rub_hands
                rub_hands(self.px)
                return True
            except Exception as e:
                logger.error(f"Error in rub_hands: {e}")
                return False
                
        elif function_name == "depressed":
            try:
                logger.info("Executing depressed animation")
                # Import and call the preset animation
                from modules.gpt.preset_actions import depressed
                depressed(self.px)
                return True
            except Exception as e:
                logger.error(f"Error in depressed: {e}")
                return False
                
        elif function_name == "keep_think":
            try:
                logger.info("Executing keep_think animation")
                # Import and call the preset animation
                from modules.gpt.preset_actions import keep_think
                keep_think(self.px)
                return True
            except Exception as e:
                logger.error(f"Error in keep_think: {e}")
                return False
                
        else:
            logger.warning(f"Unknown predefined function: {function_name}")
            return False
            
    except Exception as e:
        logger.error(f"Error executing function {function_name}: {e}")
        return False
