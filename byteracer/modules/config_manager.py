import os
import json
import asyncio
import logging
import threading
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class ConfigManager:
    """
    Manages robot configuration and user settings.
    Handles loading/saving settings to JSON and synchronizing with clients.
    """
    def __init__(self, config_dir=None):
        # Set config directory
        if config_dir is None:
            # Default to config directory in the project
            self.config_dir = Path(__file__).parent.parent / "config"
        else:
            self.config_dir = Path(config_dir)
        
        # Ensure config directory exists
        self.config_dir.mkdir(exist_ok=True)
        
        # Config file path
        self.config_file = self.config_dir / "settings.json"
        
        # Default settings
        self.settings = {
            # Sound settings
            "sound": {
                "enabled": True,
                "volume": 80,  # Master volume for all audio
                "sound_volume": 80,  # Master volume for sound effects
                "tts_volume": 80,  # Master volume for all TTS
                "tts_enabled": True,
                "tts_language": "en-US",
                "tts_audio_gain": 6,  # Gain in dB to make TTS louder
                # Individual category volumes
                "driving_volume": 80,  # For acceleration, braking, drift sounds
                "alert_volume": 90,    # For emergency/alert sounds
                "custom_volume": 80,   # For user-triggered sound effects
                "voice_volume": 95,    # For push-to-talk voice streams
                "user_tts_volume": 80, # For user-triggered TTS
                "system_tts_volume": 90, # For system/emergency TTS
                "emergency_tts_volume": 95, # For emergency TTS
            },
            
            # Camera settings
            "camera": {
                "vflip": False,
                "hflip": False,
                "local_display": False,
                "web_display": True,
                "camera_size": [1920, 1080],  # Default camera resolution [width, height]
            },
            
            # Safety settings
            "safety": {
                "collision_avoidance": True,
                "edge_detection": True,
                "auto_stop": True,
                "collision_threshold": 20,  # cm
                "edge_threshold": 0.2,
                "client_timeout": 15,  # seconds
                "emergency_cooldown": 0.1, # seconds between emergency checks
                "safe_distance_buffer": 10, # cm buffer added to collision threshold
                "battery_emergency_enabled": True, # Whether to trigger emergency on low battery
                "low_battery_threshold": 15, # percentage to trigger low battery warning
                "low_battery_warning_interval": 60, # seconds between low battery warnings
                "edge_recovery_time": 0.5, # seconds to continue backing up after edge is no longer detected
            },
            
            # Drive settings
            "drive": {
                "max_speed": 100,
                "max_turn_angle": 30,
                "acceleration_factor": 0.8,
                "enhanced_turning": True,    # Enable differential steering for better turning
                "turn_in_place": True,       # Allow turning in place when no forward/backward motion
            },
            
            # Special modes
            "modes": {
                "tracking_enabled": False,
                "circuit_mode_enabled": False,
                "demo_mode_enabled": False,
                "normal_mode_enabled": True,
            },
            
            # Github settings
            "github": {
                "branch": "working-2",
                "repo_url": "https://github.com/nayzflux/byteracer.git",
                "auto_update": True
            },

            # API settings
            "api": {
                "openai_api_key": ""
            },
            "ai": {
                "speak_pause_threshold": 1.2,
                "distance_threshold_cm": 30,
                "turn_time": 2,
                "yolo_confidence": 0.5,
                "motor_balance": 0, # -50 to +50, negative for left bias, positive for right bias
                "autonomous_speed": 0.05, # Default speed for autonomous driving (5%)
                "wait_to_turn_time": 2.0, # Time to wait before turning after seeing a turn sign (seconds)
                "stop_sign_wait_time": 2.0, # Time to wait at a stop sign (seconds)
                "stop_sign_ignore_time": 3.0, # Time to ignore stop signs after stopping (seconds)
                "traffic_light_ignore_time": 3.0, # Time to ignore traffic lights after responding (seconds)
                "target_face_area": 10.0, # Target face area for face tracking (5-30%)
                "forward_factor": 0.5, # Forward factor for face tracking (0.1-1.0)
                "face_tracking_max_speed": 0.1, # Maximum speed for face tracking (1-20%)
                "speed_dead_zone": 0.5, # Speed dead zone for face tracking (0.0-1.0)
                "turn_factor": 35.0, # Turn factor for face tracking (10.0-50.0)
            },
            "led": {
                "enabled": True,
            },
        }
        
        # Lock for thread safety
        self._lock = threading.Lock()
        self._save_task = None
        self._autosave_interval = 10  # seconds
        self._needs_save = False
        self._running = True
        
        # Load settings from file if it exists
        self._load_settings()
        
        logger.info("Config Manager initialized")
    
    def _load_settings(self):
        """Load settings from file"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    loaded_settings = json.load(f)
                
                # Deep merge with default settings to ensure all fields exist
                self._deep_merge(self.settings, loaded_settings)
                
                logger.info(f"Settings loaded from {self.config_file}")
            else:
                logger.info("No settings file found, using defaults")
                self._save_settings_now()  # Create the file with defaults
        except Exception as e:
            logger.error(f"Error loading settings: {e}")
    
    def _save_settings_now(self):
        """Immediately save settings to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.settings, f, indent=2)
            
            logger.info(f"Settings saved to {self.config_file}")
            return True
        except Exception as e:
            logger.error(f"Error saving settings: {e}")
            return False
    
    async def _autosave_task(self):
        """Task to automatically save settings when changed"""
        logger.info("Starting config autosave task")
        
        while self._running:
            try:
                await asyncio.sleep(self._autosave_interval)
                
                with self._lock:
                    if self._needs_save:
                        self._save_settings_now()
                        self._needs_save = False
            
            except asyncio.CancelledError:
                logger.info("Config autosave task cancelled")
                # Final save before exiting
                if self._needs_save:
                    self._save_settings_now()
                break
            except Exception as e:
                logger.error(f"Error in autosave task: {e}")
                await asyncio.sleep(1)
    
    async def start(self):
        """Start the autosave task"""
        self._save_task = asyncio.create_task(self._autosave_task())
        logger.info("Config autosave started")
    
    async def stop(self):
        """Stop the autosave task"""
        self._running = False
        
        if self._save_task:
            self._save_task.cancel()
            try:
                await self._save_task
            except asyncio.CancelledError:
                pass
            
            # Ensure any pending changes are saved
            with self._lock:
                if self._needs_save:
                    self._save_settings_now()
        
        logger.info("Config manager stopped")
    
    def set(self, path, value):
        """
        Set a setting by dot-notation path.
        Example: set("sound.volume", 70)
        
        Returns:
            bool: True if setting was changed, False otherwise
        """
        with self._lock:
            # Handle dot notation paths
            parts = path.split('.')
            
            # Navigate to the right part of the settings dict
            current = self.settings
            for i, part in enumerate(parts[:-1]):
                if part not in current:
                    logger.warning(f"Invalid settings path: {path}")
                    return False
                current = current[part]
            
            last_part = parts[-1]
            if last_part not in current:
                logger.warning(f"Invalid settings path: {path}")
                return False
            
            # Check if value is actually changed
            if current[last_part] == value:
                return False
            
            # Update the value
            current[last_part] = value
            self._needs_save = True
            
            logger.debug(f"Setting updated: {path} = {value}")
            return True
    
    def get(self, path=None):
        """
        Get a setting by dot-notation path.
        If path is None, returns all settings.
        
        Example: get("sound.volume")
        
        Returns:
            Any: The setting value, or None if path is invalid
        """
        with self._lock:
            if path is None:
                # Return a copy of all settings
                return dict(self.settings)
            
            # Handle dot notation paths
            parts = path.split('.')
            
            # Navigate to the right part of the settings dict
            current = self.settings
            for part in parts:
                if part not in current:
                    logger.warning(f"Invalid settings path: {path}")
                    return None
                current = current[part]
            
            return current
    
    def add_known_network(self, ssid, password):
        """
        Add a known WiFi network.
        
        Returns:
            bool: True if network was added, False if it already exists
        """
        with self._lock:
            networks = self.settings["network"]["known_networks"]
            
            # Check if network already exists
            for network in networks:
                if network.get("ssid") == ssid:
                    # Update password if network exists
                    if network.get("password") != password:
                        network["password"] = password
                        self._needs_save = True
                        logger.info(f"Updated password for network: {ssid}")
                        return True
                    else:
                        logger.info(f"Network already exists: {ssid}")
                        return False
            
            # Add new network
            networks.append({
                "ssid": ssid,
                "password": password
            })
            
            self._needs_save = True
            logger.info(f"Added new network: {ssid}")
            return True
    
    def remove_known_network(self, ssid):
        """
        Remove a known WiFi network.
        
        Returns:
            bool: True if network was removed, False if not found
        """
        with self._lock:
            networks = self.settings["network"]["known_networks"]
            
            # Find and remove the network
            for i, network in enumerate(networks):
                if network.get("ssid") == ssid:
                    del networks[i]
                    self._needs_save = True
                    logger.info(f"Removed network: {ssid}")
                    return True
            
            logger.warning(f"Network not found: {ssid}")
            return False
    
    def _deep_merge(self, target, source):
        """
        Deep merge two dictionaries.
        Values from source override target, but dictionaries are merged recursively.
        """
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                # If both are dicts, merge recursively
                self._deep_merge(target[key], value)
            else:
                # Otherwise override target with source
                target[key] = value
        
        return target
    
    def save(self):
        """Manually request settings to be saved"""
        with self._lock:
            self._needs_save = True
            # For immediate save
            return self._save_settings_now()
    
    def reset_to_defaults(self, section=None):
        """
        Reset settings to defaults.
        
        Args:
            section (str): Optional section to reset (e.g., "sound", "camera")
            
        Returns:
            bool: True if settings were reset, False otherwise
        """
        default_settings = {
            # Sound settings
            "sound": {
                "enabled": True,
                "volume": 80,  # Master volume for all audio
                "sound_volume": 80,  # Master volume for sound effects
                "tts_volume": 80,  # Master volume for all TTS
                "tts_enabled": True,
                "tts_language": "en-US",
                "tts_audio_gain": 6,  # Gain in dB to make TTS louder
                # Individual category volumes
                "driving_volume": 80,  # For acceleration, braking, drift sounds
                "alert_volume": 90,    # For emergency/alert sounds
                "custom_volume": 80,   # For user-triggered sound effects
                "voice_volume": 95,    # For push-to-talk voice streams
                "user_tts_volume": 80, # For user-triggered TTS
                "system_tts_volume": 90, # For system TTS
                "emergency_tts_volume": 95, # For emergency TTS
            },
            
            # Camera settings
            "camera": {
                "vflip": False,
                "hflip": False,
                "local_display": False,
                "web_display": True,
                "camera_size": [1920, 1080],  # Default camera resolution
            },
            
            # Safety settings
            "safety": {
                "collision_avoidance": True,
                "edge_detection": True,
                "auto_stop": True,
                "collision_threshold": 20,  # cm
                "edge_threshold": 0.2,
                "client_timeout": 15,  # seconds
                "emergency_cooldown": 0.1, # seconds between emergency checks
                "safe_distance_buffer": 10, # cm buffer added to collision threshold
                "battery_emergency_enabled": True, # Whether to trigger emergency on low battery
                "low_battery_threshold": 15, # percentage to trigger low battery warning
                "low_battery_warning_interval": 60, # seconds between low battery warnings
                "edge_recovery_time": 0.5, # seconds to continue backing up after edge is no longer detected
            },
            
            # Drive settings
            "drive": {
                "max_speed": 100,
                "max_turn_angle": 30,
                "acceleration_factor": 0.8,
                "enhanced_turning": True,    # Enable differential steering for better turning
                "turn_in_place": True,       # Allow turning in place when no forward/backward motion
            },
            
            # Special modes
            "modes": {
                "tracking_enabled": False,
                "circuit_mode_enabled": False,
                "demo_mode_enabled": False,
                "normal_mode_enabled": True,
            },
            
            # Github settings
            "github": {
                "branch": "working-2",
                "repo_url": "https://github.com/nayzflux/byteracer.git",
                "auto_update": True
            },

            # API settings
            "api": {
                "openai_api_key": ""
            },
            "ai": {
                "speak_pause_threshold": 1.2,
                "distance_threshold_cm": 30,
                "turn_time": 2,
                "yolo_confidence": 0.5,
                "motor_balance": 0, # -50 to +50, negative for left bias, positive for right bias
                "autonomous_speed": 0.05, # Default speed for autonomous driving (5%)
                "wait_to_turn_time": 2.0, # Time to wait before turning after seeing a turn sign (seconds)
                "stop_sign_wait_time": 2.0, # Time to wait at a stop sign (seconds)
                "stop_sign_ignore_time": 3.0, # Time to ignore stop signs after stopping (seconds)
                "traffic_light_ignore_time": 3.0, # Time to ignore traffic lights after responding (seconds)
                "target_face_area": 10.0, # Target face area for face tracking (5-30%)
                "forward_factor": 0.5, # Forward factor for face tracking (0.1-1.0)
                "face_tracking_max_speed": 0.1, # Maximum speed for face tracking (1-20%)
                "speed_dead_zone": 0.5, # Speed dead zone for face tracking (0.0-1.0)
                "turn_factor": 35.0, # Turn factor for face tracking (10.0-50.0)
            },
            "led": {
                "enabled": True,
            },
        }

        with self._lock:
            if section is None:
                # Reset everything except network settings
                for key, value in default_settings.items():
                    self.settings[key] = value
            elif section in default_settings:
                # Reset only specified section
                self.settings[section] = default_settings[section]
            else:
                logger.warning(f"Invalid settings section: {section}")
                return False
            
            self._needs_save = True
            logger.info(f"Reset settings to defaults: {section if section else 'all'}")
            return True