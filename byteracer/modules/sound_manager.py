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
    Handles acceleration, braking, drift sounds, custom sound effects, and WebRTC audio playback.
    """
    def __init__(self, assets_dir=None, enabled=True, volume=100):
        self.music_player = Music()
        self.enabled = enabled
        self.volume = max(0, min(100, volume))  # Master volume
        
        # Category-specific volumes (will be updated from config later)
        self.sound_volume = 80  # Sound effects master volume
        self.driving_volume = 80  # Volume for driving sounds
        self.alert_volume = 90  # Volume for alert/emergency sounds
        self.custom_volume = 80  # Volume for user-triggered sounds
        self.voice_volume = 95  # Volume for push-to-talk voice streams
        
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
        self.current_voice_channel = None  # Track the current voice stream channel
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
                    
                    # Apply the appropriate volume based on sound type
                    # First apply category volume, then apply sound master volume, then apply overall master volume
                    category_volume = self._get_category_volume(sound_type)
                    effective_volume = (self.volume / 100.0) * (self.sound_volume / 100.0) * (category_volume / 100.0)
                    sound.set_volume(effective_volume)
                    
                    pygame.mixer.Channel(channel_id).play(sound, loops=-1 if loop else 0)
                    
                    # Add to the list of current sounds for this type
                    if sound_type not in self.current_sounds:
                        self.current_sounds[sound_type] = []
                    self.current_sounds[sound_type].append(channel_id)
                    
                    logger.debug(f"Playing {sound_type} sound: {sound_file.name} on channel {channel_id}")
                    return channel_id
        
        logger.warning("No available sound channels")
        return None
    
    def _get_category_volume(self, sound_type):
        """Get the appropriate volume for a sound category"""
        if sound_type in ["acceleration", "braking", "drift"]:
            return self.driving_volume
        elif sound_type == "alerts":
            return self.alert_volume
        elif sound_type == "custom":
            return self.custom_volume
        elif sound_type == "voice":
            return self.voice_volume
        else:
            return 100  # Default to full volume for unknown categories
    
    def stop_sound(self, sound_type=None, channel_id=None):
        """
        Stop a playing sound.
        
        Args:
            sound_type (str): Type of sound to stop
            channel_id (int): Specific channel ID to stop
        """
        with self._lock:
            if channel_id is not None:
                if 0 <= channel_id < pygame.mixer.get_num_channels():
                    pygame.mixer.Channel(channel_id).stop()
                    logger.debug(f"Stopped sound on channel {channel_id}")
                    # Remove from current_sounds
                    for sound_type, channels in self.current_sounds.items():
                        if channel_id in channels:
                            self.current_sounds[sound_type].remove(channel_id)
            
            elif sound_type is not None:
                if sound_type in self.current_sounds:
                    # Stop all sounds of this type
                    for channel_id in self.current_sounds[sound_type]:
                        if 0 <= channel_id < pygame.mixer.get_num_channels():
                            pygame.mixer.Channel(channel_id).stop()
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
        if speed > 0.1:
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
            # Use the play_sound method to benefit from proper volume handling
            return self.play_sound("alerts", loop=False, name=alert_name) is not None
        
        logger.warning(f"Alert sound not found: {alert_name}")
        return False
    
    def play_custom_sound(self, sound_name):
        """Play a custom sound by name"""
        return self.play_sound("custom", loop=False, name=sound_name) is not None
    
    def play_voice_stream(self, file_path):
        """
        Play an audio stream received from push-to-talk feature.
        
        Args:
            file_path (str): Path to the temporary WAV file containing the voice data
        """
        if not self.enabled:
            return None
        
        # Stop any currently playing voice stream
        if self.current_voice_channel is not None:
            if pygame.mixer.Channel(self.current_voice_channel).get_busy():
                pygame.mixer.Channel(self.current_voice_channel).stop()
        
        with self._lock:
            # Find an available channel with higher priority for voice
            for channel_id in range(pygame.mixer.get_num_channels()):
                if not pygame.mixer.Channel(channel_id).get_busy():
                    # Load and play the sound
                    try:
                        sound = pygame.mixer.Sound(file_path)
                        
                        # Apply volume based on voice stream priority
                        effective_volume = (self.volume / 100.0) * (self.voice_volume / 100.0)
                        sound.set_volume(effective_volume)
                        
                        pygame.mixer.Channel(channel_id).play(sound)
                        self.current_voice_channel = channel_id
                        
                        logger.debug(f"Playing voice stream on channel {channel_id}")
                        return channel_id
                    except Exception as e:
                        logger.error(f"Error playing voice stream: {e}")
                        return None
        
        logger.warning("No available sound channels for voice stream")
        return None
    
    def play_file(self, file_path):
        """Play a specific sound file, volume and catergory are voice"""
        if not self.enabled:
            return None
        
        # Stop any currently playing voice stream
        if self.current_voice_channel is not None:
            if pygame.mixer.Channel(self.current_voice_channel).get_busy():
                pygame.mixer.Channel(self.current_voice_channel).stop()
        
        with self._lock:
            # Find an available channel with higher priority for voice
            for channel_id in range(pygame.mixer.get_num_channels()):
                if not pygame.mixer.Channel(channel_id).get_busy():
                    # Load and play the sound
                    try:
                        sound = pygame.mixer.Sound(file_path)
                        
                        # Apply volume based on voice stream priority
                        effective_volume = (self.volume / 100.0) * (self.voice_volume / 100.0)
                        sound.set_volume(effective_volume)
                        
                        pygame.mixer.Channel(channel_id).play(sound)
                        self.current_voice_channel = channel_id
                        
                        logger.debug(f"Playing file on channel {channel_id}")
                        return channel_id
                    except Exception as e:
                        logger.error(f"Error playing file: {e}")
                        return None
        
        logger.warning("No available sound channels for file")
        return None
    
    def set_voice_volume(self, volume):
        """Set volume for push-to-talk voice streams (0-100)"""
        self.voice_volume = max(0, min(100, volume))
        logger.info(f"Voice stream volume set to {self.voice_volume}")
        self._update_playing_sounds_volume()
    
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
        """Set master volume for all sounds (0-100)"""
        self.volume = max(0, min(100, volume))
        logger.info(f"Sound master volume set to {self.volume}")
        self._update_playing_sounds_volume()
    
    def set_sound_volume(self, volume):
        """Set volume for all sound effects (0-100)"""
        self.sound_volume = max(0, min(100, volume))
        logger.info(f"Sound effects volume set to {self.sound_volume}")
        self._update_playing_sounds_volume()
    
    def set_category_volume(self, category, volume):
        """
        Set volume for a specific sound category
        
        Args:
            category (str): Category of sound ('driving', 'alert', 'custom', 'voice', 'webrtc')
            volume (int): Volume level from 0 (mute) to 100 (max)
        """
        volume = max(0, min(100, volume))
        
        if category == "driving":
            self.driving_volume = volume
            logger.info(f"Driving sounds volume set to {volume}")
        elif category == "alert":
            self.alert_volume = volume
            logger.info(f"Alert sounds volume set to {volume}")
        elif category == "custom":
            self.custom_volume = volume
            logger.info(f"Custom sounds volume set to {volume}")
        elif category == "voice":
            self.voice_volume = volume
            logger.info(f"Voice stream volume set to {volume}")
        else:
            logger.warning(f"Unknown sound category: {category}")
            return
        
        self._update_playing_sounds_volume()
    
    def _update_playing_sounds_volume(self):
        """Update volume of all currently playing sounds"""
        with self._lock:
            for sound_type, channels in self.current_sounds.items():
                category_volume = self._get_category_volume(sound_type)
                effective_volume = (self.volume / 100.0) * (self.sound_volume / 100.0) * (category_volume / 100.0)
                
                for channel_id in channels:
                    if 0 <= channel_id < pygame.mixer.get_num_channels() and pygame.mixer.Channel(channel_id).get_busy():
                        sound = pygame.mixer.Channel(channel_id).get_sound()
                        sound.set_volume(effective_volume)

    async def shutdown(self):
        """Clean shutdown of sound manager"""
        self._running = False
        self.stop_sound()  # Stop all sound effects
        self.music_stop()  # Stop music
        
        pygame.mixer.quit()
        logger.info("Sound Manager shutdown")