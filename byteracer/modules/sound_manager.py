import os
import time
import asyncio
import threading
import logging
import random
from pathlib import Path
import pygame  # For sound effects

from robot_hat import Music

logger = logging.getLogger(__name__)

class SoundManager:
    """
    Manages sound effects and music for the robot.
    Handles acceleration, braking, drift sounds and custom sound effects.
    """
    def __init__(self, assets_dir=None, enabled=True, volume=100):
        self.music_player = Music()
        self.enabled = enabled
        self.volume = max(0, min(100, volume))
        
        # Set assets directory
        if assets_dir is None:
            # Default to assets directory in the project
            self.assets_dir = Path(__file__).parent.parent / "assets"
        else:
            self.assets_dir = Path(assets_dir)
        
        # Ensure assets directory exists
        self.assets_dir.mkdir(exist_ok=True)
        
        # Initialize pygame for sound effects
        pygame.mixer.init()
        
        # Sound categories and their files
        self.sounds = {
            "acceleration": self._load_sounds("acceleration"),
            "braking": self._load_sounds("braking"),
            "drift": self._load_sounds("drift"),
            "alerts": self._load_sounds("alerts"),
            "custom": self._load_sounds("custom"),
        }
        
        # Keep track of currently playing sounds - modified to support multiple sounds per type
        self.current_sounds = {category: [] for category in self.sounds.keys()}
        self._running = True
        self._lock = threading.Lock()
        
        # Sound state tracking
        self.is_accelerating = False
        self.is_braking = False
        self.is_drifting = False
        
        logger.info(f"Sound Manager initialized with {sum(len(s) for s in self.sounds.values())} sounds")
    
    def _load_sounds(self, category):
        """Load sound files from a category directory"""
        category_dir = self.assets_dir / category
        if not category_dir.exists():
            category_dir.mkdir(exist_ok=True)
            logger.info(f"Created sound category directory: {category}")
            return []
        
        sound_files = []
        for ext in ['.mp3', '.wav', '.ogg']:
            sound_files.extend(list(category_dir.glob(f'*{ext}')))
        
        logger.info(f"Loaded {len(sound_files)} sounds for category '{category}'")
        return sound_files
    
    def play_sound(self, sound_type, loop=False, name=None):
        """
        Play a sound of the specified type.
        
        Args:
            sound_type (str): Type of sound to play (acceleration, braking, drift, alerts, custom)
            loop (bool): Whether to loop the sound
            name (str): Optional specific sound name to play
        """
        if not self.enabled:
            return None
        
        sound_files = self.sounds.get(sound_type, [])
        if not sound_files:
            logger.warning(f"No sounds available for category '{sound_type}'")
            return None
        
        # Select a specific sound by name if provided, otherwise choose randomly
        if name:
            matching_files = [f for f in sound_files if f.stem == name]
            if matching_files:
                sound_file = matching_files[0]
            else:
                logger.warning(f"Sound '{name}' not found in category '{sound_type}', using random sound")
                sound_file = random.choice(sound_files)
        else:
            # Select a random sound from the category
            sound_file = random.choice(sound_files)
        
        with self._lock:
            # Find an available channel
            for channel_id in range(pygame.mixer.get_num_channels()):
                if not pygame.mixer.Channel(channel_id).get_busy():
                    # Load and play the sound
                    sound = pygame.mixer.Sound(str(sound_file))
                    sound.set_volume(self.volume / 100.0)
                    pygame.mixer.Channel(channel_id).play(sound, loops=-1 if loop else 0)

                    logger.info(f"Playing sound: {sound_file.name} on channel {channel_id}")
                    
                    # Add to the list of current sounds for this type
                    if sound_type not in self.current_sounds:
                        self.current_sounds[sound_type] = []
                    self.current_sounds[sound_type].append(channel_id)
                    
                    logger.debug(f"Playing {sound_type} sound: {sound_file.name} on channel {channel_id}")
                    return channel_id
        
        logger.warning("No available sound channels")
        return None
    
    def stop_sound(self, sound_type=None, channel_id=None):
        """
        Stop a playing sound.
        
        Args:
            sound_type (str): Type of sound to stop
            channel_id (int or Channel): Specific channel ID or Channel object to stop
        """
        with self._lock:
            if channel_id is not None:
                # Handle both Channel objects and integer channel IDs
                if isinstance(channel_id, pygame.mixer.Channel):
                    # Direct Channel object
                    channel_id.stop()
                    logger.debug(f"Stopped sound on Channel object")
                elif 0 <= channel_id < pygame.mixer.get_num_channels():
                    # Integer channel ID
                    pygame.mixer.Channel(channel_id).stop()
                    logger.debug(f"Stopped sound on channel {channel_id}")
                
                # Remove from current_sounds
                for sound_type, channels in self.current_sounds.items():
                    if channel_id in channels:
                        self.current_sounds[sound_type].remove(channel_id)
            
            elif sound_type is not None:
                if sound_type in self.current_sounds:
                    # Stop all sounds of this type
                    for ch in self.current_sounds[sound_type]:
                        if isinstance(ch, pygame.mixer.Channel):
                            # Direct Channel object
                            ch.stop()
                        elif 0 <= ch < pygame.mixer.get_num_channels():
                            # Integer channel ID
                            pygame.mixer.Channel(ch).stop()
                    logger.debug(f"Stopped all {sound_type} sounds")
                    self.current_sounds[sound_type] = []
            
            else:
                # Stop all sounds
                pygame.mixer.stop()
                self.current_sounds = {category: [] for category in self.sounds.keys()}
                logger.debug("Stopped all sounds")
    
    def update_driving_sounds(self, speed, turn_value, acceleration):
        """
        Update driving sounds based on the current speed, turning and acceleration.
        
        Args:
            speed (float): Current speed (-1.0 to 1.0)
            turn_value (float): Current turning value (-1.0 to 1.0)
            acceleration (float): Current acceleration
        """
        if not self.enabled:
            return
        
        # Detect acceleration, braking, and drifting states
        abs_speed = abs(speed)
        abs_turn = abs(turn_value)
        
        # Acceleration sound
        if abs_speed > 0.1 and acceleration > 0.05:
            if not self.is_accelerating:
                self.play_sound("acceleration", loop=True)
                self.is_accelerating = True
        elif self.is_accelerating:
            self.stop_sound("acceleration")
            self.is_accelerating = False
        
        # Braking sound
        if abs_speed > 0.1 and acceleration < -0.05:
            if not self.is_braking:
                self.play_sound("braking")
                self.is_braking = True
        elif self.is_braking and abs_speed < 0.05:
            self.stop_sound("braking")
            self.is_braking = False
        
        # Drift sound
        if abs_speed > 0.3 and abs_turn > 0.5:
            if not self.is_drifting:
                self.play_sound("drift", loop=True)
                self.is_drifting = True
        elif self.is_drifting and (abs_speed < 0.2 or abs_turn < 0.4):
            self.stop_sound("drift")
            self.is_drifting = False
    
    def play_alert(self, alert_name):
        """Play a specific alert sound"""
        alert_files = [f for f in self.sounds["alerts"] if f.stem == alert_name]
        if alert_files:
            # Load and play the alert sound
            sound = pygame.mixer.Sound(str(alert_files[0]))
            sound.set_volume(self.volume / 100.0)
            channel_id = pygame.mixer.find_channel()
            if channel_id:
                channel_id.play(sound)
                
                # Track the channel - store the channel object directly
                self.current_sounds["alerts"].append(channel_id)
                
                logger.debug(f"Playing alert sound: {alert_name}")
                return True
        
        logger.warning(f"Alert sound not found: {alert_name}")
        return False
    
    def play_custom_sound(self, sound_name):
        """Play a custom sound by name"""
        custom_files = [f for f in self.sounds["custom"] if f.stem == sound_name]
        if custom_files:
            self.play_sound("custom", loop=False, name=sound_name)
            return True
        
        logger.warning(f"Custom sound not found: {sound_name}")
        return False
    
    def music_play(self, file_name):
        """Play music using the Music class from robot_hat"""
        if not self.enabled:
            return False
        
        try:
            file_path = str(self.assets_dir / file_name)
            if not os.path.exists(file_path):
                logger.warning(f"Music file not found: {file_path}")
                return False
            
            self.music_player.music_play(file_path)
            logger.debug(f"Playing music: {file_name}")
            return True
        except Exception as e:
            logger.error(f"Error playing music: {e}")
            return False
    
    def music_stop(self):
        """Stop currently playing music"""
        try:
            self.music_player.music_stop()
            logger.debug("Stopped music")
            return True
        except Exception as e:
            logger.error(f"Error stopping music: {e}")
            return False
    
    def set_enabled(self, enabled):
        """Enable or disable all sounds"""
        self.enabled = enabled
        logger.info(f"Sound manager {'enabled' if enabled else 'disabled'}")
        if not enabled:
            self.stop_sound()  # Stop all sounds
            self.music_stop()
    
    def set_volume(self, volume):
        """Set volume for all sounds (0-100)"""
        self.volume = max(0, min(100, volume))
        logger.info(f"Sound volume set to {self.volume}")
        # Update volume of currently playing sounds
        with self._lock:
            for channel_id in range(pygame.mixer.get_num_channels()):
                if pygame.mixer.Channel(channel_id).get_busy():
                    sound = pygame.mixer.Channel(channel_id).get_sound()
                    sound.set_volume(self.volume / 100.0)
    
    def shutdown(self):
        """Clean shutdown of sound manager"""
        self._running = False
        self.stop_sound()  # Stop all sound effects
        self.music_stop()  # Stop music
        pygame.mixer.quit()
        logger.info("Sound Manager shutdown")