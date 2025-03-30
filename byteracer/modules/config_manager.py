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
                "volume": 80,
                "tts_enabled": True,
                "tts_volume": 80,
                "tts_language": "en-US",
            },
            
            # Camera settings
            "camera": {
                "vflip": False,
                "hflip": False,
                "local_display": False,
                "web_display": True,
            },
            
            # Safety settings
            "safety": {
                "collision_avoidance": True,
                "edge_detection": True,
                "auto_stop": True,
                "collision_threshold": 20,  # cm
                "edge_threshold": 0.2,
                "client_timeout": 15,  # seconds
            },
            
            # Drive settings
            "drive": {
                "max_speed": 100,
                "max_turn_angle": 30,
                "acceleration_factor": 0.8,
            },
            
            # Special modes
            "modes": {
                "tracking_enabled": False,
                "circuit_mode_enabled": False,
                "demo_mode_enabled": False,
            },
            
            # Network settings
            "network": {
                "mode": "wifi",  # "wifi" or "ap"
                "known_networks": [],
                "ap_name": "ByteRacer",
                "ap_password": "byteracer123",
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
                "volume": 80,
                "tts_enabled": True,
                "tts_volume": 80,
                "tts_language": "en-US",
            },
            
            # Camera settings
            "camera": {
                "vflip": False,
                "hflip": False,
                "local_display": False,
                "web_display": True,
            },
            
            # Safety settings
            "safety": {
                "collision_avoidance": True,
                "edge_detection": True,
                "auto_stop": True,
                "collision_threshold": 20,  # cm
                "edge_threshold": 0.2,
                "client_timeout": 15,  # seconds
            },
            
            # Drive settings
            "drive": {
                "max_speed": 100,
                "max_turn_angle": 30,
                "acceleration_factor": 0.8,
            },
            
            # Special modes
            "modes": {
                "tracking_enabled": False,
                "circuit_mode_enabled": False,
                "demo_mode_enabled": False,
            },
            
            # Network settings are not reset by default
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