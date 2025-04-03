import asyncio
import threading
from robot_hat import TTS
import time
import logging
import os
import uuid
import subprocess
import signal

logger = logging.getLogger(__name__)

class TTSManager:
    """
    Manages Text-to-Speech functionality with asynchronous operation.
    Prevents TTS operations from blocking the main program flow.
    """
    def __init__(self, lang="en-US", enabled=True, volume=80):
        self.lang = lang
        self.enabled = enabled
        self.volume = volume
        self._queue = asyncio.Queue()
        self._speaking = False
        self._current_priority = 0
        self._lock = threading.Lock()
        self._running = True
        self._task = None
        self._current_process = None
        self._clear_temp_files()
        logger.info(f"TTS Manager initialized (lang={lang}, volume={volume})")
    
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
        if not self.enabled:
            logger.debug(f"TTS disabled, skipping: '{text}'")
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
                
                # Speak the text in a separate thread to avoid blocking
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
        
        # Kill any running speech process
        with self._lock:
            current_process = self._current_process
            # Clear the queue while we have the lock
            self.clear_queue()
            # Reset speaking state
            self._speaking = False
            self._current_priority = 0
            self._current_process = None
        
        # Now handle the process termination outside the lock since it involves awaits
        if current_process and current_process.poll() is None:
            try:
                # Try to terminate the process
                current_process.terminate()
                
                # Wait a short time for it to terminate gracefully - outside the lock
                for _ in range(10):  # Wait up to 0.5 seconds
                    if current_process.poll() is not None:
                        break
                    await asyncio.sleep(0.05)
                
                # If it's still running, force kill it
                if current_process.poll() is None:
                    current_process.kill()
                    
                logger.debug("Stopped current speech process")
            except Exception as e:
                logger.error(f"Error stopping speech process: {e}")
        
        # Find and clean up any temporary TTS files that might be in use
        await asyncio.to_thread(self._cleanup_temp_files)
        
        return True
        
    def _cleanup_temp_files(self):
        """Clean up temporary TTS files that might still be in use"""
        try:
            for filename in os.listdir("/tmp"):
                if (filename.startswith("tts_") and filename.endswith(".wav")) or \
                   (filename.startswith("tts_vol_") and filename.endswith(".wav")):
                    try:
                        file_path = os.path.join("/tmp", filename)
                        os.remove(file_path)
                        logger.debug(f"Cleaned up TTS temp file: {filename}")
                    except Exception as e:
                        logger.warning(f"Failed to remove temp file {filename}: {e}")
        except Exception as e:
            logger.warning(f"Error cleaning up temporary TTS files: {e}")
    
    def _speak(self, text):
        """Execute the actual TTS operation"""
        try:
            logger.debug(f"Speaking: '{text}' (volume: {self.volume})")
            
            # Generate a unique temp file name for this specific TTS operation
            temp_file = f"/tmp/tts_{uuid.uuid4().hex}.wav"
            
            # Generate the TTS wave file - without background execution
            pico_cmd = f'pico2wave -l {self.lang} -w {temp_file} "{text}"'
            
            # Execute command and wait for it to complete
            pico_process = subprocess.run(pico_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if pico_process.returncode != 0:
                logger.error(f"TTS pico2wave error: {pico_process.stderr.decode()}")
                return False
            
            # Apply volume adjustment if needed
            if self.volume != 100:
                # Calculate volume multiplier (0-1 range for sox)
                vol_multiplier = max(0.0, min(1.0, self.volume / 100.0))
                
                # Create a new temporary file with adjusted volume
                volume_file = f"/tmp/tts_vol_{uuid.uuid4().hex}.wav"
                
                # Use sox to adjust volume (create a new file instead of playing directly)
                vol_cmd = f'sox {temp_file} {volume_file} vol {vol_multiplier}'
                logger.debug(f"Adjusting volume with sox: multiplier {vol_multiplier}")
                
                vol_process = subprocess.run(vol_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if vol_process.returncode != 0:
                    logger.error(f"Volume adjustment error: {vol_process.stderr.decode()}")
                    # If volume adjustment fails, fall back to the original file
                    play_cmd = f'aplay {temp_file}'
                else:
                    # Play the volume-adjusted file and then clean it up
                    play_cmd = f'aplay {volume_file}'
                    
                    # We'll clean up the original temp file now, volume file later
                    try:
                        os.remove(temp_file)
                        temp_file = volume_file  # For cleanup in finally block
                    except Exception as e:
                        logger.warning(f"Failed to remove original TTS file: {e}")
            else:
                # Just play the original file at full volume
                play_cmd = f'aplay {temp_file}'
                logger.debug("Playing with standard aplay (full volume)")
            
            # Play the audio file - store the process so we can terminate it if needed
            self._current_process = subprocess.Popen(play_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # Wait for the process to complete
            return_code = self._current_process.wait()
            if return_code != 0:
                stderr = self._current_process.stderr.read().decode() if self._current_process.stderr else "Unknown error"
                logger.error(f"Audio playback error: {stderr}")
            
            # Clear the current process reference
            self._current_process = None
            
            return True
        except Exception as e:
            logger.error(f"TTS error while speaking '{text}': {e}")
            self._current_process = None
            return False
        finally:
            # Clean up temp files
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
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