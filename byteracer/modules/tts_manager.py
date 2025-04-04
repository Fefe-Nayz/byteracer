import asyncio
import threading
import time  # Added missing import for time.sleep()
import logging
import os
import uuid
import subprocess
from pathlib import Path
import pygame

logger = logging.getLogger(__name__)

class TTSManager:
    """
    Manages Text-to-Speech functionality with asynchronous operation.
    Uses pygame for audio playback exactly like the sound_manager - completely non-blocking.
    """
    def __init__(self, sound_manager=None, lang="en-US", enabled=True, volume=80):
        self.lang = lang
        self.enabled = enabled
        self.volume = volume  # Master TTS volume
        self.user_tts_volume = 80  # Volume for user-triggered TTS
        self.system_tts_volume = 90  # Volume for system/emergency TTS
        self.emergency_tts_volume = 95  # Volume for emergency TTS
        self.sound_manager = sound_manager
        self._queue = asyncio.Queue()
        self._speaking = False
        self._current_priority = 0
        self._lock = threading.Lock()
        self._running = True
        self._task = None
        self._current_process = None
        
        # TTS pygame setup
        self._reserve_tts_channel()
        
        # Current TTS channel
        self._tts_channel_id = None
        self._tts_sound = None
        
        # Clean up any leftover temp files
        self._clear_temp_files()
        
        logger.info(f"TTS Manager initialized (lang={lang}, volume={volume})")
    
    def _reserve_tts_channel(self):
        """Make sure we have a dedicated channel in pygame mixer for TTS"""
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        
        # Reserve the last channel for TTS
        self.tts_channel_max = pygame.mixer.get_num_channels() - 1
        
        # Add a tracking category in sound manager if possible
        if self.sound_manager and "tts" not in self.sound_manager.current_sounds:
            self.sound_manager.current_sounds["tts"] = []
    
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
        # Stop any currently playing TTS
        await self.stop_speech()
        logger.info("TTS processing loop stopped")
    
    async def say(self, text, priority=0, blocking=False, lang=None):
        """
        Add a phrase to the TTS queue.
        
        Args:
            text (str): Text to be spoken
            priority (int): Priority level (higher means more important)
            blocking (bool): If True, wait until speech is completed (not recommended)
            lang (str): Language for the TTS (overrides instance language)
        """

        logger.info(f"Request to say: '{text}' in lang '{lang}' with priority {priority}")

        if lang is None:
            lang = self.lang
        if not self.enabled:
            logger.debug(f"TTS disabled, skipping: '{text}'")
            return

        # Put in queue with priority
        await self._queue.put((priority, text, lang))
        logger.debug(f"Added to TTS queue: '{text}' (priority {priority})")
        
        if blocking:
            # Wait until this specific message is processed (not recommended)
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
                
                priority, text, lang = await self._queue.get()
                
                with self._lock:
                    self._speaking = True
                    self._current_priority = priority
                
                # Generate the speech in a separate thread to avoid blocking
                # Important: We DON'T wait for the playback to finish in this thread
                await asyncio.to_thread(self._generate_and_play_speech, text, lang)
                
                # Mark as done IMMEDIATELY - don't wait for audio to finish
                self._queue.task_done()
                
                # Reset speaking state for next item in queue
                with self._lock:
                    self._speaking = False
                    self._current_priority = 0
                
            except asyncio.CancelledError:
                logger.info("TTS queue processor cancelled")
                break
            except Exception as e:
                logger.error(f"Error in TTS queue processor: {e}")
                await asyncio.sleep(1)  # Avoid tight loop on error
    
    async def stop_speech(self):
        """Stop the currently playing speech and clear the queue"""
        logger.info("Stopping current speech and clearing queue")
        
        # Clear the queue
        self.clear_queue()
        
        with self._lock:
            # Reset speaking state
            self._speaking = False
            self._current_priority = 0
            
            # Kill any running generation process
            if self._current_process and self._current_process.poll() is None:
                try:
                    self._current_process.terminate()
                    self._current_process = None
                except Exception as e:
                    logger.error(f"Error stopping TTS generation process: {e}")
            
            # Get current channel
            current_channel = self._tts_channel_id
        
        # Stop playback now - OUTSIDE the lock, following sound_manager pattern
        if current_channel is not None:
            pygame.mixer.Channel(current_channel).stop()
            logger.debug(f"Stopped TTS on channel {current_channel}")
            
            # Clean up tracking in sound manager
            if self.sound_manager and "tts" in self.sound_manager.current_sounds:
                with self.sound_manager._lock:
                    if current_channel in self.sound_manager.current_sounds["tts"]:
                        self.sound_manager.current_sounds["tts"].remove(current_channel)
        
        # Reset reference
        self._tts_channel_id = None
        self._tts_sound = None
        
        # Clean up temporary files
        await asyncio.to_thread(self._cleanup_temp_files)
        
    def _generate_and_play_speech(self, text, lang=None):
        """Generate speech file and start playback - but don't wait for it to finish"""
        if lang is None:
            lang = self.lang

        if not self.enabled:
            return False
        
        temp_file = None
        final_file = None
        
        try:
            # Generate the TTS wave file
            temp_file = f"/tmp/tts_{uuid.uuid4().hex}.wav"
            final_file = temp_file
            pico_cmd = f'pico2wave -l {lang} -w {temp_file} "{text}"'
            logger.debug(f"Generating TTS for: '{text}'")
            
            # Generate the audio file
            self._current_process = subprocess.Popen(pico_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            result = self._current_process.wait()
            self._current_process = None
            
            if result != 0:
                stderr = self._current_process.stderr.read().decode() if self._current_process.stderr else "Unknown error"
                logger.error(f"TTS pico2wave error: {stderr}")
                return False
            
            # Apply volume adjustment if needed
            # Determine effective volume based on priority
            # Priority 0: user-triggered TTS (lower priority)
            # Priority 1: system TTS (medium priority)
            # Priority 2+: emergency TTS (highest priority)
            if self._current_priority >= 2:
                priority_volume = self.emergency_tts_volume
            elif self._current_priority == 1:
                priority_volume = self.system_tts_volume
            else:
                priority_volume = self.user_tts_volume
                
            effective_volume = (self.volume / 100.0) * (priority_volume / 100.0)
            
            if effective_volume != 1.0:
                volume_file = f"/tmp/tts_vol_{uuid.uuid4().hex}.wav"
                
                # Use sox to adjust volume
                vol_multiplier = max(0.0, min(1.0, effective_volume))
                vol_cmd = f'sox {temp_file} {volume_file} vol {vol_multiplier}'
                
                self._current_process = subprocess.Popen(vol_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                result = self._current_process.wait()
                self._current_process = None
                
                if result == 0:
                    # Use the volume-adjusted file
                    try:
                        os.remove(temp_file)
                        final_file = volume_file
                        temp_file = None  # Prevent double cleanup
                    except Exception as e:
                        logger.warning(f"Failed to remove original TTS file: {e}")
                else:
                    logger.error(f"Volume adjustment error, using original file")
            
            # Now play the file using pygame
            try:
                # Load the sound
                sound = pygame.mixer.Sound(final_file)
                
                # Set initial volume based on master * category volume
                sound.set_volume(effective_volume)
                
                # Stop any current TTS first - critical to avoid blocking
                if self._tts_channel_id is not None:
                    pygame.mixer.Channel(self._tts_channel_id).stop()
                
                # Find a free channel
                channel_id = None
                for i in range(pygame.mixer.get_num_channels()):
                    if not pygame.mixer.Channel(i).get_busy():
                        channel_id = i
                        break
                
                if (channel_id is None):
                    # If no channel is available, use the reserved TTS channel anyway
                    channel_id = self.tts_channel_max
                    pygame.mixer.Channel(channel_id).stop()  # Force stop anything on this channel
                
                # Store references to current sound and channel
                self._tts_sound = sound  # Keep reference to prevent garbage collection
                self._tts_channel_id = channel_id
                
                # Add to tracking in sound manager
                if self.sound_manager and "tts" in self.sound_manager.current_sounds:
                    with self.sound_manager._lock:
                        if channel_id not in self.sound_manager.current_sounds["tts"]:
                            self.sound_manager.current_sounds["tts"].append(channel_id)
                
                # Play the sound - NON-BLOCKING
                pygame.mixer.Channel(channel_id).play(sound)
                logger.debug(f"Started TTS playback on channel {channel_id}")
                
                # Set up end callback to clean up temp file
                # This is a bit tricky since pygame doesn't have built-in callbacks
                # We'll handle temp file cleanup separately
                
                return True
                
            except Exception as e:
                logger.error(f"Error during pygame TTS playback: {e}")
                return False
                
        except Exception as e:
            logger.error(f"TTS error while generating/playing '{text}': {e}")
            return False
        finally:
            # Schedule temp file cleanup after a delay
            # We can't delete the file immediately since it's being played
            # But we don't want to block waiting for playback to finish
            self._schedule_file_cleanup(final_file, temp_file)
    
    def _schedule_file_cleanup(self, final_file, temp_file=None):
        """Schedule temp file cleanup after a delay - non-blocking"""
        def delayed_cleanup():
            # Wait a bit to ensure file isn't in use anymore
            time.sleep(30)  # Generous delay to ensure playback is done
            try:
                if temp_file and os.path.exists(temp_file):
                    os.remove(temp_file)
                if final_file and final_file != temp_file and os.path.exists(final_file):
                    os.remove(final_file)
                logger.debug("Cleaned up TTS temp files after delay")
            except Exception as e:
                logger.warning(f"Error in delayed TTS file cleanup: {e}")
        
        # Start a separate thread to clean up - completely non-blocking
        cleanup_thread = threading.Thread(target=delayed_cleanup)
        cleanup_thread.daemon = True
        cleanup_thread.start()
    
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
                            except (PermissionError, OSError):
                                logger.warning(f"Permission error removing temp file {filename}, may still be in use")
                    except Exception as e:
                        logger.warning(f"Failed to remove temp file {filename}: {e}")
        except Exception as e:
            logger.warning(f"Error cleaning up temporary TTS files: {e}")
    
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
                    try:
                        os.remove(os.path.join("/tmp", filename))
                        logger.debug(f"Removed leftover TTS temp file: {filename}")
                    except Exception:
                        pass  # Ignore errors during startup cleanup
        except Exception as e:
            logger.warning(f"Error cleaning up TTS temp files: {e}")
    
    def is_speaking(self):
        """Check if TTS is currently speaking"""
        with self._lock:
            return self._speaking or (self._tts_channel_id is not None and 
                   pygame.mixer.Channel(self._tts_channel_id).get_busy())
    
    def clear_queue(self, min_priority=None):
        """
        Clear the TTS queue.
        
        Args:
            min_priority (int): If provided, only clear messages with lower priority
        """
        with self._lock:
            if min_priority is not None:
                # Only remove messages with lower priority
                remaining = []
                while not self._queue.empty():
                    try:
                        item = self._queue.get_nowait()
                        if item[0] >= min_priority:
                            remaining.append(item)
                        self._queue.task_done()
                    except Exception:
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
                    except Exception:
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
        Set the master TTS volume level
        
        Args:
            volume (int): Volume level from 0 (mute) to 100 (max)
        """
        # Ensure volume is between 0 and 100
        self.volume = max(0, min(100, volume))
        logger.info(f"TTS master volume set to {self.volume}%")
        
        # Update volume of currently playing TTS if any
        self._update_current_tts_volume()
            
        return self.volume
    
    def set_user_tts_volume(self, volume):
        """
        Set the volume level for user-triggered TTS (priority 0)
        
        Args:
            volume (int): Volume level from 0 (mute) to 100 (max)
        """
        # Ensure volume is between 0 and 100
        self.user_tts_volume = max(0, min(100, volume))
        logger.info(f"User TTS volume set to {self.user_tts_volume}%")
        
        # Update volume if currently playing and is user TTS
        self._update_current_tts_volume()
        
        return self.user_tts_volume
    
    def set_system_tts_volume(self, volume):
        """
        Set the volume level for system/emergency TTS (priority 1+)
        
        Args:
            volume (int): Volume level from 0 (mute) to 100 (max)
        """
        # Ensure volume is between 0 and 100
        self.system_tts_volume = max(0, min(100, volume))
        logger.info(f"System TTS volume set to {self.system_tts_volume}%")
        
        # Update volume if currently playing and is system TTS
        self._update_current_tts_volume()
        
        return self.system_tts_volume
    
    def set_emergency_tts_volume(self, volume):
        """
        Set the volume level for emergency TTS (priority 2+)
        
        Args:
            volume (int): Volume level from 0 (mute) to 100 (max)
        """
        # Ensure volume is between 0 and 100
        self.emergency_tts_volume = max(0, min(100, volume))
        logger.info(f"Emergency TTS volume set to {self.emergency_tts_volume}%")
        
        # Update volume if currently playing and is emergency TTS
        self._update_current_tts_volume()
        
        return self.emergency_tts_volume
    
    def get_emergency_tts_volume(self):
        """Get the current emergency TTS volume level"""
        return self.emergency_tts_volume
    
    def _update_current_tts_volume(self):
        """Update the volume of currently playing TTS based on its priority"""
        with self._lock:
            if self._tts_sound and self._current_priority is not None:
                # Determine which volume to use based on priority
                if self._current_priority >= 2:
                    priority_volume = self.emergency_tts_volume
                elif self._current_priority == 1:
                    priority_volume = self.system_tts_volume
                else:
                    priority_volume = self.user_tts_volume
                effective_volume = (self.volume / 100.0) * (priority_volume / 100.0)
                self._tts_sound.set_volume(effective_volume)
                logger.debug(f"Updated TTS volume to {effective_volume*100:.1f}%")
    
    def get_volume(self):
        """Get the current TTS master volume level"""
        return self.volume
    
    def get_user_tts_volume(self):
        """Get the current user TTS volume level"""
        return self.user_tts_volume
    
    def get_system_tts_volume(self):
        """Get the current system TTS volume level"""
        return self.system_tts_volume