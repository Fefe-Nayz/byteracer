import asyncio
import threading
from robot_hat import TTS
import time
import logging

logger = logging.getLogger(__name__)

class TTSManager:
    """
    Manages Text-to-Speech functionality with asynchronous operation.
    Prevents TTS operations from blocking the main program flow.
    """
    def __init__(self, lang="en-US", enabled=True, volume=80):
        self.tts = TTS()
        self.tts.lang(lang)
        self.enabled = enabled
        self.volume = volume
        self._queue = asyncio.Queue()
        self._speaking = False
        self._current_priority = 0
        self._lock = threading.Lock()
        self._running = True
        self._task = None
        logger.info("TTS Manager initialized")
    
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
    
    def _speak(self, text):
        """Execute the actual TTS operation"""
        try:
            logger.debug(f"Speaking: '{text}'")
            self.tts.say(text)
            return True
        except Exception as e:
            logger.error(f"TTS error while speaking '{text}': {e}")
            return False
    
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
    
    def set_volume(self, volume):
        """Set the TTS volume (0-100)"""
        self.volume = max(0, min(100, volume))
        logger.info(f"TTS volume set to {self.volume}")
    
    def set_language(self, lang):
        """Set the TTS language"""
        self.tts.lang(lang)
        logger.info(f"TTS language set to {lang}")