import asyncio
import threading
import time
import logging
import os
import uuid
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

class TTSManager:
    """
    Manages Text-to-Speech functionality with asynchronous operation.
    Prevents TTS operations from blocking the main program flow.
    Uses SoundManager for audio playback to ensure consistent behavior.
    """
    def __init__(self, sound_manager=None, lang="en-US", enabled=True, volume=80):
        self.lang = lang
        self.enabled = enabled
        self.volume = volume
        self.sound_manager = sound_manager  # Store reference to sound manager
        self._queue = asyncio.Queue()
        self._speaking = False
        self._current_priority = 0
        self._lock = threading.Lock()
        self._running = True
        self._task = None
        self._current_process = None
        self._current_channel = None
        
        # Create a dedicated TTS category for the sound manager if it doesn't exist
        if sound_manager:
            self._create_tts_sound_category()
        
        self._clear_temp_files()
        logger.info(f"TTS Manager initialized (lang={lang}, volume={volume})")
    
    def _create_tts_sound_category(self):
        """Create a TTS category for the sound manager"""
        # Check if the sound manager already has a TTS category
        if "tts" not in self.sound_manager.sounds:
            # Add a new category for TTS
            tts_dir = self.sound_manager.assets_dir / "tts"
            if not tts_dir.exists():
                tts_dir.mkdir(exist_ok=True)
                logger.info("Created TTS sound category directory")
            
            # Add the category to sound manager's sounds
            self.sound_manager.sounds["tts"] = []
            # Add empty list for tracking currently playing TTS sounds
            self.sound_manager.current_sounds["tts"] = []
            logger.info("Added TTS category to sound manager")
    
    async def start(self):
        """Start the TTS processing loop"""
        self._task = asyncio.create_task(self._process_queue())
        logger.info("TTS processing loop started")
        
    async def stop(self):
        """Stop the TTS processing loop"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("TTS processing loop stopped")
    
    async def say(self, text, priority=0, blocking=False):
        """
        Add a phrase to the TTS queue.
        
        Args:
            text (str): Text to be spoken
            priority (int): Priority level (higher means more important)
            blocking (bool): If True, wait until speech is completed
        """
        if not self.enabled or not self.sound_manager:
            logger.debug(f"TTS disabled or sound manager not available, skipping: '{text}'")
            return

        # Put in queue with priority
        await self._queue.put((priority, text))
        logger.debug(f"Added to TTS queue: '{text}' (priority {priority})")
        
        if blocking:
            # Wait until this specific message is processed
            while self._speaking and self._queue.qsize() > 0:
                await asyncio.sleep(0.1)
    
    async def _process_queue(self):
        """Process the TTS queue asynchronously"""
        logger.info("Starting TTS queue processor")
        while self._running:
            try:
                if self._queue.empty():
                    await asyncio.sleep(0.1)
                    continue
                
                priority, text = await self._queue.get()
                
                with self._lock:
                    self._speaking = True
                    self._current_priority = priority
                
                # Generate and speak the text in a separate thread to avoid blocking
                speaking_task = asyncio.to_thread(self._speak, text)
                await speaking_task
                
                with self._lock:
                    self._speaking = False
                    self._current_priority = 0
                
                self._queue.task_done()
                
            except asyncio.CancelledError:
                logger.info("TTS queue processor cancelled")
                break
            except Exception as e:
                logger.error(f"Error in TTS queue processor: {e}")
                await asyncio.sleep(1)  # Avoid tight loop on error
    
    async def stop_speech(self):
        """Stop the currently playing speech and clear the queue"""
        logger.info("Stopping current speech and clearing queue")
        
        with self._lock:
            # Clear the queue
            self.clear_queue()
            
            # Reset speaking state
            self._speaking = False
            self._current_priority = 0
            
            # Kill any running pico2wave or sox processes
            if self._current_process and self._current_process.poll() is None:
                try:
                    self._current_process.terminate()
                    self._current_process = None
                except Exception as e:
                    logger.error(f"Error stopping TTS generation process: {e}")
            
            # Store channel ID to stop
            channel_to_stop = self._current_channel
            self._current_channel = None
        
        # Stop playback via sound manager if there's a current channel
        if channel_to_stop is not None and self.sound_manager:
            self.sound_manager.stop_sound(channel_id=channel_to_stop)
        
        # Clean up temporary files in a separate thread
        await asyncio.to_thread(self._cleanup_temp_files)
        
        return True
        
    def _cleanup_temp_files(self):
        """Clean up temporary TTS files"""
        try:
            for filename in os.listdir("/tmp"):
                if (filename.startswith("tts_") and filename.endswith(".wav")) or \
                   (filename.startswith("tts_vol_") and filename.endswith(".wav")):
                    try:
                        file_path = os.path.join("/tmp", filename)
                        if os.path.exists(file_path):
                            try:
                                os.remove(file_path)
                                logger.debug(f"Cleaned up TTS temp file: {filename}")
                            except PermissionError:
                                logger.warning(f"Permission error removing temp file {filename}, may still be in use")
                    except Exception as e:
                        logger.warning(f"Failed to remove temp file {filename}: {e}")
        except Exception as e:
            logger.warning(f"Error cleaning up temporary TTS files: {e}")
    
    def _wait_for_playback_completion(self, channel_id):
        """Wait for playback to complete on the specified channel"""
        if channel_id is None or not self.sound_manager:
            return
            
        # Get a reference to pygame mixer channels from the sound manager
        try:
            import pygame
            
            # Wait while the channel is busy, but also check if we should stop
            start_time = time.time()
            while pygame.mixer.Channel(channel_id).get_busy():
                time.sleep(0.05)
                
                # Check if we're still supposed to be speaking (in case stop_speech was called)
                with self._lock:
                    if not self._speaking or self._current_channel != channel_id:
                        break
                        
                # Failsafe - don't wait forever (5 minutes max)
                if time.time() - start_time > 300:
                    logger.warning("TTS playback timeout reached, stopping wait")
                    break
                    
        except Exception as e:
            logger.error(f"Error waiting for TTS playback completion: {e}")
    
    def _speak(self, text):
        """Execute the actual TTS operation"""
        if not self.sound_manager:
            logger.error("Sound manager not available for TTS playback")
            return False
            
        temp_file = None
        final_file = None
            
        try:
            logger.debug(f"Speaking: '{text}' (volume: {self.volume})")
            
            # Generate a unique temp file name for this specific TTS operation
            temp_file = f"/tmp/tts_{uuid.uuid4().hex}.wav"
            final_file = temp_file
            
            # Generate the TTS wave file
            pico_cmd = f'pico2wave -l {self.lang} -w {temp_file} "{text}"'
            
            self._current_process = subprocess.Popen(pico_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            result = self._current_process.wait()
            
            if result != 0:
                stderr = self._current_process.stderr.read().decode() if self._current_process.stderr else "Unknown error"
                logger.error(f"TTS pico2wave error: {stderr}")
                return False
            
            # Reset the process reference
            self._current_process = None
            
            # Apply volume adjustment if needed
            if self.volume != 100:
                volume_file = f"/tmp/tts_vol_{uuid.uuid4().hex}.wav"
                
                # Use sox to adjust volume
                vol_multiplier = max(0.0, min(1.0, self.volume / 100.0))
                vol_cmd = f'sox {temp_file} {volume_file} vol {vol_multiplier}'
                
                self._current_process = subprocess.Popen(vol_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                result = self._current_process.wait()
                self._current_process = None
                
                if result == 0:
                    # Use the volume-adjusted file and clean up the original
                    try:
                        os.remove(temp_file)
                        final_file = volume_file
                        temp_file = None  # Prevent double cleanup
                    except Exception as e:
                        logger.warning(f"Failed to remove original TTS file: {e}")
                else:
                    logger.error(f"Volume adjustment error, using original file")
            
            # Check if we're still supposed to be speaking
            with self._lock:
                if not self._speaking:
                    logger.debug("Speech was canceled while generating audio")
                    return False
            
            # Play the generated WAV file directly using pygame
            try:
                import pygame
                
                with self._lock:
                    # Load the sound
                    sound = pygame.mixer.Sound(final_file)
                    
                    # Set the volume (adjusting for sound manager's volume as well)
                    effective_volume = (self.volume / 100.0) * (self.sound_manager.volume / 100.0)
                    sound.set_volume(effective_volume)
                    
                    # Find an available channel
                    channel_id = None
                    for i in range(pygame.mixer.get_num_channels()):
                        if not pygame.mixer.Channel(i).get_busy():
                            channel_id = i
                            break
                    
                    if channel_id is None:
                        logger.warning("No available channel for TTS playback")
                        return False
                    
                    # Play on the found channel
                    pygame.mixer.Channel(channel_id).play(sound)
                    
                    # Store the channel ID for later stopping
                    self._current_channel = channel_id
                    
                    # Add to sound manager's tracking
                    if "tts" not in self.sound_manager.current_sounds:
                        self.sound_manager.current_sounds["tts"] = []
                    self.sound_manager.current_sounds["tts"].append(channel_id)
                    
                    logger.debug(f"Playing TTS on channel {channel_id}")
                
                # Wait for playback to complete or be stopped
                self._wait_for_playback_completion(channel_id)
                
                # Reset current channel if we're still the current speaker
                with self._lock:
                    if self._current_channel == channel_id:
                        self._current_channel = None
                
                # Remove from tracking in sound manager
                with self.sound_manager._lock:
                    if "tts" in self.sound_manager.current_sounds and channel_id in self.sound_manager.current_sounds["tts"]:
                        self.sound_manager.current_sounds["tts"].remove(channel_id)
                
                logger.debug("TTS playback completed")
                return True
                
            except Exception as e:
                logger.error(f"Error during pygame TTS playback: {e}")
                return False
                
        except Exception as e:
            logger.error(f"TTS error while speaking '{text}': {e}")
            self._current_process = None
            return False
        finally:
            # Clean up temp files
            try:
                if temp_file and os.path.exists(temp_file):
                    os.remove(temp_file)
                if final_file and final_file != temp_file and os.path.exists(final_file):
                    os.remove(final_file)
            except Exception as e:
                logger.warning(f"Failed to remove temporary TTS file: {e}")
    
    def _clear_temp_files(self):
        """Clear any temporary TTS files that might be left over from previous runs"""
        try:
            # Clear default temp file that might be used by startup.sh
            if os.path.exists("/tmp/tts.wav"):
                os.remove("/tmp/tts.wav")
                logger.debug("Removed default TTS temp file")
            
            # Clear any of our own temp files that may be left over
            for filename in os.listdir("/tmp"):
                if filename.startswith("tts_") and filename.endswith(".wav"):
                    os.remove(os.path.join("/tmp", filename))
                    logger.debug(f"Removed leftover TTS temp file: {filename}")
        except Exception as e:
            logger.warning(f"Error cleaning up TTS temp files: {e}")
    
    def is_speaking(self):
        """Check if TTS is currently speaking"""
        with self._lock:
            return self._speaking
    
    def clear_queue(self, min_priority=None):
        """
        Clear the TTS queue.
        
        Args:
            min_priority (int): If provided, only clear messages with lower priority
        """
        with self._lock:
            if min_priority is not None:
                # Only remove messages with lower priority
                # Note: This is a bit tricky with asyncio.Queue, so we recreate it
                remaining = []
                while not self._queue.empty():
                    try:
                        item = self._queue.get_nowait()
                        if item[0] >= min_priority:
                            remaining.append(item)
                        self._queue.task_done()
                    except:
                        break
                
                # Create a new queue with remaining items
                self._queue = asyncio.Queue()
                for item in remaining:
                    self._queue.put_nowait(item)
            else:
                # Clear entire queue
                while not self._queue.empty():
                    try:
                        self._queue.get_nowait()
                        self._queue.task_done()
                    except:
                        break
        
        logger.debug(f"TTS queue cleared (min_priority={min_priority})")
    
    def set_enabled(self, enabled):
        """Enable or disable TTS functionality"""
        self.enabled = enabled
        logger.info(f"TTS {'enabled' if enabled else 'disabled'}")
        if not enabled:
            self.clear_queue()
    
    def set_language(self, lang):
        """Set the TTS language"""
        self.lang = lang
        logger.info(f"TTS language set to {lang}")
        
    def set_volume(self, volume):
        """
        Set the TTS volume level
        
        Args:
            volume (int): Volume level from 0 (mute) to 100 (max)
        """
        # Ensure volume is between 0 and 100
        self.volume = max(0, min(100, volume))
        logger.info(f"TTS volume set to {self.volume}%")
        return self.volume
        
    def get_volume(self):
        """Get the current TTS volume level"""
        return self.volume