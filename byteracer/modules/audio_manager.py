import asyncio
import logging
import time
import json
import pyaudio
import wave
import io
import base64
import threading
from queue import Queue
from typing import Optional

class AudioManager:
    """
    Manages robot microphone recording and streaming audio to clients.
    
    This manager handles capturing audio from the robot's microphone and 
    streaming it to connected clients over WebSocket.
    """
    def __init__(self):
        """Initialize the AudioManager"""
        self.running = False
        self.recording_task = None
        self.websocket = None
        self.audio_queue = Queue()
        self.format = pyaudio.paInt16  # 16-bit audio
        self.channels = 1              # Mono
        self.rate = 16000              # 16kHz sampling rate
        self.chunk_size = 1024         # Audio chunks
        self.pyaudio = None
        self.stream = None
        self.worker_thread = None
        self.active_recording = False
        
        # Logging
        self.logger = logging.getLogger(__name__)
        self.logger.info("AudioManager initialized")

    async def start(self):
        """Start the audio manager"""
        self.running = True
        # Start worker thread for sending audio
        self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.worker_thread.start()
        self.logger.info("AudioManager started")

    async def stop(self):
        """Stop the audio manager"""
        self.running = False
        
        # Stop recording if active
        await self.stop_recording()
        
        # Wait for worker thread to finish
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=1.0)
            
        self.logger.info("AudioManager stopped")

    async def start_recording(self, websocket = None):
        """Start recording audio from the microphone and streaming to client"""
        self.websocket = websocket
        if self.active_recording:
            self.logger.info("Recording already active, ignoring start request")
            return
        
        self.logger.info("Starting microphone recording")
        self.active_recording = True
        
        # Initialize PyAudio in the recording task to ensure it's in the correct thread
        self.recording_task = asyncio.create_task(self._record_audio())
        
    async def stop_recording(self):
        """Stop recording audio from the microphone"""
        if not self.active_recording:
            return
            
        self.logger.info("Stopping microphone recording")
        self.active_recording = False
        
        if self.recording_task:
            # Wait for recording task to finish
            try:
                await self.recording_task
            except asyncio.CancelledError:
                pass
            self.recording_task = None
        
        # Close PyAudio stream and terminate PyAudio
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception as e:
                self.logger.error(f"Error closing audio stream: {e}")
            self.stream = None
            
        if self.pyaudio:
            try:
                self.pyaudio.terminate()
            except Exception as e:
                self.logger.error(f"Error terminating PyAudio: {e}")
            self.pyaudio = None
            
    async def _record_audio(self):
        """Record audio from microphone and add chunks to queue"""
        try:
            # Initialize PyAudio
            self.pyaudio = pyaudio.PyAudio()
            
            # Open a stream for recording
            self.stream = self.pyaudio.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk_size
            )
            
            self.logger.info("Audio recording started")
            
            # Record audio in chunks while active
            while self.active_recording:
                if self.stream.is_active():
                    # Read audio chunk from microphone
                    data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                    
                    # Put in queue for sending to client
                    self._encode_and_queue(data)
                    
                    # Small delay to prevent tight loop
                    await asyncio.sleep(0.01)
                else:
                    await asyncio.sleep(0.1)
                    
        except Exception as e:
            self.logger.error(f"Error in audio recording: {e}")
            self.active_recording = False
            
        finally:
            # Make sure to clean up even if there's an error
            if self.stream:
                try:
                    self.stream.stop_stream()
                    self.stream.close()
                except Exception:
                    pass
                self.stream = None
                
            if self.pyaudio:
                try:
                    self.pyaudio.terminate()
                except Exception:
                    pass
                self.pyaudio = None
            
            self.logger.info("Audio recording stopped")
    
    def _encode_and_queue(self, audio_data):
        """Convert audio chunk to WAV format and encode as base64 for sending"""
        try:
            # Create an in-memory WAV file
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(self.pyaudio.get_sample_size(self.format))
                wf.setframerate(self.rate)
                wf.writeframes(audio_data)
                
            # Get the WAV data and encode as base64
            wav_data = wav_buffer.getvalue()
            base64_audio = base64.b64encode(wav_data).decode('utf-8')
            
            # Add data URI prefix for browser compatibility
            audio_uri = f"data:audio/wav;base64,{base64_audio}"
            
            # Add to queue for sending
            self.audio_queue.put(audio_uri)
            
        except Exception as e:
            self.logger.error(f"Error encoding audio data: {e}")
            
    def _process_queue(self):
        """Worker thread to process audio queue and send to WebSocket"""
        while self.running:
            try:
                # Get next audio chunk with a timeout
                try:
                    audio_data = self.audio_queue.get(timeout=0.5)
                except Queue.Empty:
                    continue
                
                # Skip if no WebSocket or queue too large (prevent backlog)
                if not self.websocket or self.audio_queue.qsize() > 10:
                    self.audio_queue.task_done()
                    continue
                    
                # Create WebSocket message
                message = json.dumps({
                    "name": "audio_stream",
                    "data": {
                        "audioData": audio_data,
                        "timestamp": int(time.time() * 1000)
                    },
                    "createdAt": int(time.time() * 1000)
                })
                
                # Schedule sending on the event loop
                asyncio.run_coroutine_threadsafe(
                    self._send_audio(message), 
                    asyncio.get_event_loop()
                )
                
                # Mark as done in the queue
                self.audio_queue.task_done()
                
            except Exception as e:
                self.logger.error(f"Error in audio worker thread: {e}")
                time.sleep(0.1)  # Prevent tight loop on error
                
    async def _send_audio(self, message):
        """Send audio chunk over WebSocket"""
        if not self.websocket:
            return
            
        try:
            await self.websocket.send(message)
        except Exception as e:
            self.logger.error(f"Error sending audio over WebSocket: {e}")
