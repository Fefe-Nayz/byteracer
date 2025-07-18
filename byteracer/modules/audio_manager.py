import asyncio
import logging
import time
import json
import pyaudio
import wave
import io
import base64
import threading
from queue import Queue, Empty, Full               # ← added Full
from typing import Optional, List, Dict, Any


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
        self.send_queue = Queue()  # Queue for messages to be sent
        
        # Audio configuration - will try different configurations in order
        self.format = pyaudio.paInt16  # 16-bit audio
        self.channels = 1              # Mono
        # Try different sample rates - list them in order of preference
        self.sample_rates = [44100]
        self.rate = self.sample_rates[0]  # Start with the first rate
        self.chunk_size = 12288           # Audio chunks (will be reset)
        self.frame_ms = 20                # ← new: size of callback frame (ms)
        self.chunk_ms = 250               # ← new: size of packet sent (ms)

        self.pyaudio = None
        self.stream = None
        self.worker_thread = None
        self.active_recording = False
        self.device_index = None          # Will auto-detect input device

        # New runtime helpers
        self.capture_queue = None         # ← raw PCM from callback
        self.encode_task = None           # ← assembles 250 ms chunks

        # Logging
        self.logger = logging.getLogger(__name__)
        self.logger.info("AudioManager initialized")

    def set_websocket(self, websocket):
        """Set the WebSocket connection for streaming audio"""
        self.websocket = websocket
        self.logger.info("WebSocket set for audio streaming")

    async def start(self):
        """Start the audio manager"""
        self.running = True
        
        # Start worker thread for processing audio
        self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.worker_thread.start()
        
        # Start sender task in the asyncio event loop
        asyncio.create_task(self._sender_task())
        
        self.logger.info("AudioManager started")
        
        # Find available input devices
        await self._find_input_device()

    async def stop(self):
        """Stop the audio manager"""
        self.running = False
        
        # Stop recording if active
        await self.stop_recording()
        
        # Wait for worker thread to finish
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=1.0)
            
        self.logger.info("AudioManager stopped")

    async def _find_input_device(self):
        """Find a suitable input device"""
        try:
            p = pyaudio.PyAudio()
            info = p.get_host_api_info_by_index(0)
            num_devices = info.get('deviceCount', 0)
            
            self.logger.info(f"Found {num_devices} audio devices")
            
            # First look for specific input devices
            for i in range(num_devices):
                device_info = p.get_device_info_by_index(i)
                self.logger.info(
                    f"Device {i}: {device_info['name']}, "
                    f"inputs: {device_info['maxInputChannels']}"
                )

                if (
                    device_info["maxInputChannels"] > 0
                    and (
                        "USB" in device_info["name"]
                        or "input" in device_info["name"].lower()
                        or "mic" in device_info["name"].lower()
                    )
                ):
                    self.device_index = i
                    self.logger.info(
                        f"Selected preferred input device: "
                        f"{device_info['name']} (index {i})"
                    )
                    break

            # If no preferred device found, use default input device
            if self.device_index is None:
                for i in range(num_devices):
                    device_info = p.get_device_info_by_index(i)
                    if device_info["maxInputChannels"] > 0:
                        self.device_index = i
                        self.logger.info(
                            f"Selected default input device: "
                            f"{device_info['name']} (index {i})"
                        )
                        break
            
            p.terminate()
            
            if self.device_index is None:
                self.logger.error("No input device found!")
                
        except Exception as e:
            self.logger.error(f"Error finding input devices: {e}")

    async def start_recording(self, websocket=None):
        """Start recording audio from the microphone and streaming to client"""
        if websocket:
            self.websocket = websocket
            
        if self.active_recording:
            self.logger.info("Recording already active, ignoring start request")
            return
        
        self.logger.info("Starting microphone recording")
        self.active_recording = True

        # Queue for raw PCM frames from callback
        self.capture_queue = Queue(maxsize=100)

        # Initialize PyAudio in the recording task
        self.recording_task = asyncio.create_task(self._record_audio())
        
    async def stop_recording(self):
        """Stop recording audio from the microphone"""
        if not self.active_recording:
            return
            
        self.logger.info("Stopping microphone recording")
        self.active_recording = False
        
        if self.recording_task:
            try:
                await self.recording_task
            except asyncio.CancelledError:
                pass
            self.recording_task = None

        # stop encode task (if still running)
        if self.encode_task:
            self.encode_task.cancel()
            try:
                await self.encode_task
            except asyncio.CancelledError:
                pass
            self.encode_task = None

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
            
    async def _try_open_stream(self, p, rate, use_callback=False):
        """Try to open a stream with a specific sample rate"""
        try:
            kwargs = dict(
                format=self.format,
                channels=self.channels,
                rate=rate,
                input=True,
                frames_per_buffer=self.chunk_size,
            )
            if use_callback:
                kwargs["stream_callback"] = self._pyaudio_callback

            if self.device_index is None:
                stream = p.open(**kwargs)
            else:
                kwargs["input_device_index"] = self.device_index
                stream = p.open(**kwargs)

            self.logger.info(
                f"Successfully opened audio stream with sample rate: {rate}Hz"
            )
            return stream, rate
            
        except Exception as e:
            self.logger.warning(f"Failed to open stream with rate {rate}Hz: {e}")
            return None, None
            
    async def _record_audio(self):
        """Record audio from microphone and add chunks to queue"""
        try:
            # Initialize PyAudio
            self.pyaudio = pyaudio.PyAudio()
            
            # Try different sample rates in order of preference
            stream = None
            rate = None
            
            for sample_rate in self.sample_rates:
                # 20 ms of frames for this rate
                self.chunk_size = int(sample_rate * self.frame_ms / 1000)
                stream, rate = await self._try_open_stream(
                    self.pyaudio, sample_rate, use_callback=True
                )
                if stream:
                    break
            
            if not stream:
                self.logger.error("Could not open audio stream with any sample rate")
                self.active_recording = False
                return
                
            self.stream = stream
            self.rate = rate
            self.stream.start_stream()

            # Start assembler / encoder
            self.encode_task = asyncio.create_task(self._encode_pcm_loop())

            self.logger.info("Audio recording started (callback mode)")

            while self.active_recording:
                await asyncio.sleep(0.1)

        except Exception as e:
            self.logger.error(f"Error in audio recording: {e}")
            
        finally:
            # Make sure to clean up even if there's an error
            self.active_recording = False

            if self.encode_task:
                self.encode_task.cancel()
                try:
                    await self.encode_task
                except asyncio.CancelledError:
                    pass
                self.encode_task = None

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

    def _pyaudio_callback(self, in_data, frame_count, time_info, status):
        """Runs in PortAudio thread: enqueue raw PCM quickly."""
        if self.active_recording and self.capture_queue:
            try:
                self.capture_queue.put_nowait(in_data)
            except Full:
                pass  # drop if queue is full
        return (None, pyaudio.paContinue)

    async def _encode_pcm_loop(self):
        pcm_per_ms = int(self.rate * 2 / 1000)          # 2 bytes per mono frame
        target_bytes = pcm_per_ms * self.chunk_ms       # bytes in 250 ms
        pcm_buffer = bytearray()
        loop = asyncio.get_running_loop()

        while self.active_recording or not self.capture_queue.empty():
            data = await loop.run_in_executor(None, self._capture_get_blocking)
            if data is None:
                continue

            pcm_buffer.extend(data)

            while len(pcm_buffer) >= target_bytes:
                chunk = bytes(pcm_buffer[:target_bytes])
                del pcm_buffer[:target_bytes]
                self._encode_and_queue(chunk)

    def _capture_get_blocking(self):
        """Blocking get for use in executor."""
        try:
            return self.capture_queue.get(timeout=0.5)
        except Empty:
            return None

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
                except Empty:  # Use imported Empty exception
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
                
                # Add to send queue for the asyncio task to handle
                self.send_queue.put(message)
                
                # Mark as done in the queue
                self.audio_queue.task_done()
                
            except Exception as e:
                self.logger.error(f"Error in audio worker thread: {e}")
                time.sleep(0.1)  # Prevent tight loop on error
    
    async def _sender_task(self):
        """Asyncio task that sends WebSocket messages from the queue"""
        while self.running:
            try:
                # Check if there are messages to send
                try:
                    # Use get_nowait to avoid blocking the asyncio event loop
                    if not self.send_queue.empty():
                        message = self.send_queue.get_nowait()
                        await self._send_audio(message)
                        self.send_queue.task_done()
                except Empty:
                    pass  # No messages to process
                
                # Sleep a short time to avoid tight loop
                await asyncio.sleep(0.01)
            except Exception as e:
                self.logger.error(f"Error in sender task: {e}")
                await asyncio.sleep(0.1)  # Longer sleep on error
                
    async def _send_audio(self, message):
        """Send audio chunk over WebSocket"""
        if not self.websocket:
            return
            
        try:
            await self.websocket.send(message)
        except Exception as e:
            self.logger.error(f"Error sending audio over WebSocket: {e}")
