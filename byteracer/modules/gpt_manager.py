import os
import io
import time
import json
import base64
import logging
import asyncio
import tempfile
import traceback
import subprocess
from pathlib import Path
from PIL import Image
from typing import Dict, List, Any, Optional, Union
from openai import OpenAI, AsyncOpenAI
from modules.sensor_manager import RobotState
from modules.script_runner import run_script_in_isolated_environment, ScriptCancelledException
import speech_recognition as sr
import sox
from io import BytesIO
from datetime import datetime
import asyncio
import tempfile
import os
import json

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ScriptCancelledException(Exception):
    """Raised when a custom script is cancelled."""
    pass

class GPTManager:
    """
    Manages interactions with GPT models to control the robot based on natural language commands.
    Uses structured outputs to perform various actions like:
      - Motor control (set speed for DC motors, set angle for servomotors)
      - Camera feed analysis
      - Sound playback
      - Text-to-speech
      - Running custom scripts
    """
    
    def __init__(self, px, camera_manager, tts_manager, sound_manager, sensor_manager, config_manager, aicamera_manager):
        """
        Initialize the GPT manager with references to other system components.
        
        Args:
            px: Picarx instance for hardware control.
            camera_manager: Manager for accessing the camera feed.
            tts_manager: TTS manager for text-to-speech output.
            sound_manager: Sound manager for audio playback.
            sensor_manager: Sensor manager for accessing robot sensors.
            config_manager: Configuration manager for accessing settings.
            aicamera_manager: AI Camera manager for computer vision features.
        """
        self.px = px
        self.camera_manager = camera_manager
        self.tts_manager = tts_manager
        self.sound_manager = sound_manager
        self.sensor_manager = sensor_manager
        self.config_manager = config_manager
        self.aicamera_manager = aicamera_manager

        self.robot_state_enum = RobotState
        
        api_settings = self.config_manager.get("api")
        self.api_key = os.environ.get("OPENAI_API_KEY") or api_settings.get("openai_api_key", "")
        self.model = api_settings.get("model", "gpt-4.1-2025-04-14")
        
        if not self.api_key:
            logger.warning("OPENAI_API_KEY not found in environment variables or settings")
        
        # Configure OpenAI client
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url="https://api.openai.com/v1"
        )
        self.whisper_client = OpenAI(api_key=self.api_key)
        
        self.temp_dir = Path(tempfile.gettempdir()) / "byteracer_scripts"
        os.makedirs(self.temp_dir, exist_ok=True)
        logger.info(f"Using temporary directory for scripts: {self.temp_dir}")
        
        self.active_processes = {}
        self.is_processing = False
        self.gpt_command_cancelled = False
        self.current_response_id = None
          # Conversation mode properties
        self.is_conversation_active = False
        self.conversation_cancelled = False
        self.pause_threshold = 1.2
        
    def _listen_and_transcribe_blocking(self, mic_ready_callback=None) -> str:
        """
        Record until silence, return the transcript.  If realtime=True, prints
        partials as they arrive.
        
        Args:
            mic_ready_callback: Optional callback function to call when the microphone
                               is ready to receive input.
                               
        Returns:
            str: Transcribed text, or empty string if cancelled.
        """
        # 1) set up recognizer exactly as before
        r = sr.Recognizer()
        r.dynamic_energy_adjustment_damping = 0.16
        r.dynamic_energy_ratio = 1.6
        r.pause_threshold = self.pause_threshold
        CHUNK = 8192

        # 2) whisper call
        def _whisper(audio: sr.AudioData) -> str:
            # Check if conversation was cancelled during recording
            if self.conversation_cancelled:
                logger.info("Transcription cancelled, returning empty string")
                return ""
                
            client = self.whisper_client
            wav = BytesIO(audio.get_wav_data()); wav.name = "speech.wav"
            res = client.audio.transcriptions.create(
                model="whisper-1",
                file=wav,
                language=None,
                prompt="this is the conversation between me and a robot"
            )
            return res.text.strip()

        # 3B) blocking mode
        with sr.Microphone(chunk_size=CHUNK) as src:
            logger.info("Adjusting for ambient noise...")
            r.adjust_for_ambient_noise(src)
            
            # Signal that the microphone is ready to receive input
            if mic_ready_callback:
                logger.info("Microphone ready, calling mic_ready_callback")
                mic_ready_callback()
            
            # Check if conversation was cancelled during setup
            if self.conversation_cancelled:
                logger.info("Listening cancelled before it started, returning empty string")
                return ""
                
            logger.info("Listening for speech...")
            audio = r.listen(src)
            
        return _whisper(audio)

    def _synthesize_and_save_blocking(
        self,
        text: str,
        voice: str = "echo",
        volume_db: int = 3
    ) -> str:
        """
        Use OpenAI TTS  sox gain. Returns absolute path to final WAV.
        """
        if not text.strip():
            raise ValueError("Cannot synthesise empty text.")

        tts_dir = self.temp_dir / "tts"
        tts_dir.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%y-%m-%d_%H-%M-%S")
        raw = tts_dir / f"{stamp}_raw.wav"
        out = tts_dir / f"{stamp}_{volume_db}dB.wav"

        client = OpenAI(api_key=self.api_key)
        with client.audio.speech.with_streaming_response.create(
            model="gpt-4o-mini-tts",
            voice=voice,
            input=text,
            response_format="wav",
            speed=1,
        ) as resp:
            resp.stream_to_file(str(raw))

        tfm = sox.Transformer()
        tfm.vol(volume_db)
        tfm.build(str(raw), str(out))
        return str(out)
    
    async def create_new_conversation(self, websocket=None):
        """
        Reset the conversation by clearing the current response ID.
        
        Returns:
            bool: True if successful, False otherwise.
        """
        if not self.api_key:
            if websocket:
                await self._send_gpt_status_update(websocket, "error", "OpenAI API key not configured.")
            return False
        
        try:
            # Reset the conversation by clearing the current response ID
            self.current_response_id = None
            logger.info("Created new conversation (reset response ID)")
            
            if websocket:
                await self._send_gpt_status_update(websocket, "progress", "Created new conversation thread.")
            
            return True
        except Exception as e:
            logger.error(f"Error creating new conversation: {e}")
            if websocket:
                await self._send_gpt_status_update(websocket, "error", f"Failed to create new conversation: {str(e)}")
            return False        
    async def process_gpt_command(self, prompt: str, use_camera: bool = False, websocket = None, new_conversation=False, use_ai_voice: bool = False, conversation_mode: bool = False) -> bool:        
        """
        Process a GPT command with optional camera feed inclusion.
        
        Args:
            prompt: The natural language command from the user.
            use_camera: Whether to include the camera feed.
            websocket: Optional websocket connection for status updates.
            new_conversation: Whether to start a new conversation (reset thread).
            use_ai_voice: Whether to use AI-powered TTS voice for responses.
            conversation_mode: Whether to start a continuous conversation mode.
            
        Returns:
            bool: Success status.
        """
        # If we're in conversation mode, we need to reset the cancellation flag first
        self.conversation_cancelled = False
        if conversation_mode:

            # Capture the running event loop
            loop = asyncio.get_running_loop()
            mic_ready_event = asyncio.Event()
            def mic_ready_callback(loop=loop):
                async def notify_mic_ready():
                    await self._send_gpt_status_update(
                        websocket, 
                        "progress", 
                        "Microphone ready. Listening for your voice input...",
                        {"mic_status": "ready"}
                    )
                # Use the captured loop
                asyncio.run_coroutine_threadsafe(
                    notify_mic_ready(),
                    loop
                )
            # Start listening with the callback
            logger.info("Starting conversation mode recording")
            prompt = await asyncio.get_running_loop().run_in_executor(
                None, 
                lambda: self._listen_and_transcribe_blocking(lambda: mic_ready_callback(loop))
            )
            
            # Check if the conversation was cancelled during recording
            if self.conversation_cancelled:
                logger.info("Conversation was cancelled during recording, stopping process")
                if websocket:
                    await self._send_gpt_status_update(websocket, "cancelled", "Conversation recording cancelled")
                return False
                
            # If we got an empty prompt (e.g., no speech detected or whisper failed)
            if not prompt or prompt.strip() == "":
                logger.info("Empty prompt received in conversation mode, stopping process")
                if websocket:
                    await self._send_gpt_status_update(
                        websocket, 
                        "error", 
                        "No speech detected or speech recognition failed. Please try again."
                    )
                return False
            
            self.is_conversation_active = True
            logger.info(f"Recognized text for conversation mode: {prompt}")
            if websocket:
                await websocket.send(json.dumps({
                    "name": "speech_recognition",
                    "data": {
                        "text": prompt,
                    },
                    "timestamp": time.time()
                }))   
                     
        if self.is_processing:            
            if websocket:
                await self._send_gpt_status_update(websocket, "error", "Already processing a command")
            return False
        
        
        try:
            self.gpt_command_cancelled = False
            self.is_processing = True

            if not self.api_key:
                await self.tts_manager.say("OpenAI API key not configured.", priority=1)
                if websocket:
                    await self._send_gpt_status_update(websocket, "error", "API key missing")
                return False
            
            self.sensor_manager.robot_state = self.robot_state_enum.GPT_CONTROLLED

            if websocket:
                await self._send_gpt_status_update(websocket, "starting", "Processing your request with GPT")

            # Reset conversation if requested
            if new_conversation and self.current_response_id:
                if websocket:
                    await self._send_gpt_status_update(websocket, "progress", "Starting a new conversation...")
                await self.create_new_conversation(websocket)
            
            image_data = None
            
            # Get camera image if requested and available
            if use_camera and self.camera_manager:
                if websocket:
                    await self._send_gpt_status_update(websocket, "progress", "Capturing camera image...")
                
                # Check if camera is in RUNNING state
                camera_status = self.camera_manager.get_status()
                if camera_status["state"] == "RUNNING":
                    image_data = await self._get_camera_image_for_api()
                    if not image_data:
                        await self.tts_manager.say("Unable to access the camera feed. Processing without image.", priority=1)
                        if websocket:
                            await self._send_gpt_status_update(websocket, "warning", "Camera feed not available, proceeding without image")
                else:
                    await self.tts_manager.say("Camera is not active. Processing without image.", priority=1)
                    if websocket:
                        await self._send_gpt_status_update(websocket, "warning", "Camera not active, proceeding without image")
            
            # Prepare API request with instructions
            if websocket:
                await self._send_gpt_status_update(websocket, "progress", "Sending request to GPT...")
            
            # Build the input content list
            input_content = []
            
            # Add text input
            input_content.append({
                "type": "input_text",
                "text": prompt
            })
            
            # Add image input if available
            if image_data:
                input_content.append({
                    "type": "input_image",
                    "image_url": f"data:image/jpeg;base64,{image_data}"
                })

            # Define the schema for structured output
            schema = {
    "type": "object",
    "properties": {
      "action_type": {
        "type": "string",
        "enum": [
          "python_script",
          "predefined_function",
          "motor_sequence",
          "none"
        ],
        "description": "Primary action to perform. Select only one. 'none' indicates that only text output is provided."
      },
      "python_script": {
        "type": "string",
        "description": "A Python script to be executed on the robot. Non-empty only when action_type is 'python_script'."
      },
      "predefined_functions": {
        "type": "array",
        "description": "An array of function calls to your pre-defined functions. Non-empty only when action_type is 'predefined_function'.",
        "items": {
          "type": "object",
          "properties": {
            "function_name": {
              "type": "string",
              "description": "The name of the function to be called."
            },
            "parameters": {              
              "type": "object",
              "description": "A JSON object containing the parameters for the function.",
              "properties": {
                "sound_name": {"type": ["string", "null"], "description": "Name of sound to play"},
                "volume": {"type": ["number", "null"], "description": "Volume level (0-100)"},
                "enabled": {"type": ["boolean", "null"], "description": "Enable/disable flag"},
                "threshold": {"type": ["number", "null"], "description": "Threshold value for sensors"},
                "factor": {"type": ["number", "null"], "description": "Factor value for calculations"},
                "priority": {"type": ["number", "null"], "description": "Priority level for operations"},
                "timeout": {"type": ["number", "null"], "description": "Timeout value in seconds"},
                "gain": {"type": ["number", "null"], "description": "Gain value for audio"},
                "category": {"type": ["string", "null"], "description": "Category name"},
                "vflip": {"type": ["boolean", "null"], "description": "Vertical flip for camera"},
                "hflip": {"type": ["boolean", "null"], "description": "Horizontal flip for camera"},
                "width": {"type": ["number", "null"], "description": "Width dimension"},
                "height": {"type": ["number", "null"], "description": "Height dimension"},
                "local_display": {"type": ["boolean", "null"], "description": "Local display setting"},                
                "web_display": {"type": ["boolean", "null"], "description": "Web display setting"},
                "mode": {"type": ["string", "null"], "description": "Mode for the robot. Available modes: 'normal', 'tracking', 'circuit', 'demo'."},
                "text": {"type": ["string", "null"], "description": "Text for TTS output"},
                "language": {"type": ["string", "null"], "description": "Language for TTS output. Available languages: 'en-US', 'en-GB', 'de-DE', 'es-ES', 'fr-FR', 'it-IT'."}
              },
              "required": ["sound_name", "volume", "enabled", "threshold", "factor", "priority", "timeout", "gain", "category", "vflip", "hflip", "width", "height", "local_display", "web_display", "mode", "text", "language"],
              "additionalProperties": False
            }
          },
          "required": [
            "function_name",
            "parameters"
          ],
          "additionalProperties": False
        }
      },
      "motor_sequence": {
        "type": "array",
        "description": "A sequence of motor commands grouped by motor. Each item represents one motor and its scheduled actions.",
        "items": {
          "type": "object",
          "properties": {
            "motor_id": {
              "type": "string",
              "description": "Identifier for the motor. Must be one of: 'rear_left', 'rear_right', 'front', 'cam_pan', 'cam_tilt'."
            },
            "actions": {
              "type": "array",
              "description": "A list of actions for this motor, each with a timestamp, a command, and a value.",
              "items": {
                "type": "object",
                "properties": {
                  "timestamp": {
                    "type": "number",
                    "description": "Time (in seconds) at which the action should start."
                  },
                  "command": {
                    "type": "string",
                    "description": "Command to execute: either 'set_speed' for DC motors or 'set_angle' for servomotors."
                  },
                  "value": {
                    "type": "number",
                    "description": "Numeric value for the command (speed or angle)."
                  }
                },
                "required": [
                  "timestamp",
                  "command",
                  "value"
                ],
                "additionalProperties": False
              }
            }
          },
          "required": [
            "motor_id",
            "actions"
          ],
          "additionalProperties": False
        }
      },      "text": {
        "type": "string",
        "description": "A textual message for TTS output and on-screen feedback."
      },
      "language": {
        "type": "string",
        "enum": ["en-US", "en-GB", "de-DE", "es-ES", "fr-FR", "it-IT"],
        "description": "The language for text-to-speech output. You should always specify a language code."
      }
    },
    "required": [
      "action_type",
      "python_script",
      "predefined_functions",
      "motor_sequence",
      "text",
      "language"
    ],
    "additionalProperties": False
  }
            
            # Create Responses API request
            try:
                if websocket:
                    await self._send_gpt_status_update(websocket, "progress", "Processing with GPT model...")
                
                # Prepare the request with/without previous response ID for conversation continuity
                request_params = {
                    "model": self.model,
                    "input": [{"role": "user", "content": input_content}],
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "schema": schema,
                            "name": "robot_action",
                            "strict": True
                        }
                    },                    "instructions": """
You are ByteRacer, a small AI-powered robot car with real-world interaction capabilities.

HARDWARE CAPABILITIES:
- MOTORS (5 controllable devices):
  • "rear_left": DC motor - speed range -100 to 100
  • "rear_right": DC motor - speed range -100 to 100
  • "front": Steering servo - angle range -30 to 30 degrees
  • "cam_pan": Camera pan servo - angle range -90 to 90 degrees
  • "cam_tilt": Camera tilt servo - angle range -35 to 65 degrees
- SENSORS:
  • Front ultrasonic distance sensor (returns cm)
  • Bottom line-following sensors (array of values)
  • Camera for real-time visual analysis
- AUDIO:
  • Text-to-speech capability
  • Sound effect playback

AVAILABLE ACTIONS:
1. GENERATE PYTHON SCRIPT (action_type: "python_script"):
   • Scripts run in an isolated environment with existing instances
   • Use predefined objects: px, tts, sound, get_camera_image()
   • Follow strict asynchronous patterns: "await" all async functions
   • DO NOT create infinite loops or processes that can't be interrupted
   • DO NOT make repetitive TTS calls
   • DO NOT create new instances of hardware controllers
   
   AVAILABLE PYTHON SCRIPT FUNCTIONS:
   
   The `px` object provides these methods to control the robot, none of them are asynchronous, thoes are the only ones you can use:
   • px.set_motor_speed(motor_id, speed): Controls individual motors
     - motor_id: 1=rear_left, 2=rear_right
     - speed: -100 to 100
     - CRITICAL: For FORWARD motion, use POSITIVE for rear_left and NEGATIVE for rear_right
   • px.forward(speed): Moves forward at specified speed (0-100)
   • px.backward(speed): Moves backward at specified speed (0-100)
   • px.stop(): Stops all motors
   • px.set_dir_servo_angle(angle): Sets steering angle (-30 to 30 degrees)
   • px.set_cam_pan_angle(angle): Sets camera pan angle (-90 to 90 degrees)
   • px.set_cam_tilt_angle(angle): Sets camera tilt angle (-35 to 65 degrees)
   • px.get_distance(): Gets ultrasonic sensor reading (in cm)
   • px.get_line_sensor_value(): Gets line follower sensor values
   • px.get_grayscale_value(): Gets grayscale sensor reading
   • px.reset(): Reset all servos and motors to default positions
   
   For camera image processing:
   • get_camera_image(): Returns the camera image as raw bytes from camera, it's an async function
   
   For text-to-speech:
   • tts.say("Your message", priority=1, lang="en-US", blocking=False): Speaks message, This is not an async function
     - priority: 1=high, 2=medium, 3=low
     - lang: "en-US", "en-GB", "de-DE", "es-ES", "fr-FR", "it-IT"
     - blocking: True=wait for completion, False=non-blocking
   
   For sound effects:
   • sound.play_sound("custom", sound_name): Plays a specific sound effect
     - Available sounds: "alarm", "aurores", "bruh", etc. (see full list above)
   
   For timing (always use await for sleep):
   • await asyncio.sleep(seconds): Asynchronous sleep, pauses execution
   • DO NOT use time.sleep() in scripts - it blocks the event loop

   SCRIPT EXECUTION CONTEXT:
    - The execution environment already imports and provides modules such as asyncio, threading, time, json, and traceback.
    - Never re-import or redefine these modules. In particular, do not assign to or override asyncio (e.g. do not write asyncio = ... or def asyncio()).
    - NEVER IMPORT ASYNCIO
    - Do not use blocking functions like time.sleep(); always use asynchronous delays (await asyncio.sleep(seconds)).
    - You can use opencv for image processing

   SCRIPT EXECUTION GUIDELINES:
    - Always validate image data before processing
    - get_camera_image() is an asynchronous function that returns returns the camera image as raw bytes
    - Do not assign or redefine asyncio, which is a built-in module. Only use it to call asyncio.sleep or similar functions.
    - Use proper async/await patterns with asyncio
    - Use await asyncio.sleep() not time.sleep() for waiting
    - Always include proper error handling
    - Remember: Your code is executed in a sandboxed environment. Do not create infinite loops, blocking calls, or instantiate new hardware controllers.

    This is how your generated script will be executed. Take the necessary measures and precautions to ensure that your script will run correctly in this environment.

    ```py

Script execution environment for safely running ChatGPT-generated code.
Provides isolation, cancellation support, and error reporting.

import asyncio
import logging
import traceback
import time
import json
from typing import Dict, Any, Optional, Callable
import concurrent.futures
import multiprocessing
import queue as queue_mod
import sys
import os
import signal

logger = logging.getLogger(__name__)

class ScriptCancelledException(Exception):
    Raised when a script is cancelled by user request.
    pass

async def run_script_in_isolated_environment(
    script_code: str,
    px,
    get_camera_image,
    tts_manager,
    sound_manager,
    gpt_manager,
    websocket=None,
    run_in_background=False
) -> tuple[bool, dict|None]:
    
    Executes user-generated scripts in an isolated thread with proper
    cancellation support and comprehensive error handling.
    
    Args:
        script_code: The Python code to execute
        px: Picarx instance for hardware control
        get_camera_image: Function to get camera image
        tts_manager: TTS manager for text-to-speech
        sound_manager: Sound manager for audio playback
        gpt_manager: GPT manager reference for cancellation checks
        websocket: Optional websocket for error reporting
        run_in_background: Whether to run the script in background
        
    Returns:
        bool: Success status
    
    
    script_name = f"script_{int(time.time())}"
    script_done_event = multiprocessing.Event()
    result_queue = multiprocessing.Queue()
    script_result = {"success": False, "error": None, "traceback": None}
    gpt_manager.websocket = websocket
    full_script = _build_script_with_environment(script_code)

    def run_script_in_process(result_queue, script_done_event):
        try:
            import asyncio
            import threading
            import time
            import json
            import traceback
            local_env = {"ScriptCancelledException": ScriptCancelledException,
                         "asyncio": asyncio,
                         "time": time,
                         "json": json,
                         "traceback": traceback,
                         "threading": threading}
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            exec(full_script, local_env)
            user_script = local_env.get("user_script")
            if not user_script:
                result_queue.put({"error": "Script compilation failed"})
                return
            loop.run_until_complete(
                user_script(px, get_camera_image, logging.getLogger("script_runner"), tts_manager, sound_manager, gpt_manager, result_queue)
            )
            result_queue.put({"success": True})
        except ScriptCancelledException as e:
            result_queue.put({"cancelled": str(e)})
        except Exception as e:
            tb = traceback.format_exc()
            result_queue.put({"error": str(e), "traceback": tb})
        finally:
            script_done_event.set()

    process = multiprocessing.Process(target=run_script_in_process, args=(result_queue, script_done_event))
    process.start()
    gpt_manager.active_processes[script_name] = {"process": process, "done_event": script_done_event, "result_queue": result_queue}
    logger.info(f"Running script '{script_name}' in separate process")

    # Wait for process to finish or be cancelled
    while process.is_alive() and not gpt_manager.gpt_command_cancelled:
        await asyncio.sleep(0.1)
        try:
            result = result_queue.get_nowait()
            if "success" in result and result["success"]:
                script_result["success"] = True
                break
            elif "error" in result:
                script_result["error"] = result["error"]
                script_result["traceback"] = result.get("traceback", "")
                if websocket and hasattr(gpt_manager, "_send_gpt_status_update"):
                    await gpt_manager._send_gpt_status_update(websocket, "error", f"Script error: {result['error']}", {"traceback": result.get("traceback", "")})
                break
            elif "cancelled" in result:
                script_result["error"] = result["cancelled"]
                if websocket and hasattr(gpt_manager, "_send_gpt_status_update"):
                    await gpt_manager._send_gpt_status_update(websocket, "cancelled", result["cancelled"])
                break
        except queue_mod.Empty:
            pass
    # If cancelled, forcibly terminate
    if gpt_manager.gpt_command_cancelled and process.is_alive():
        process.terminate()
        process.join(timeout=2)
        if process.is_alive():
            os.kill(process.pid, signal.SIGKILL)
            logger.warning(f"Script '{script_name}' forcibly killed with SIGKILL.")
            if websocket and hasattr(gpt_manager, "_send_gpt_status_update"):
                await gpt_manager._send_gpt_status_update(
                    websocket, "error",
                    "Script was forcibly killed (SIGKILL). Hardware may need to be reset."
                )
        logger.info(f"Script '{script_name}' forcibly terminated due to cancellation.")
        if websocket and hasattr(gpt_manager, "_send_gpt_status_update"):
            await gpt_manager._send_gpt_status_update(websocket, "cancelled", "Script cancelled by user.")
    # Always stop/reset motors from the main process after script ends
    try:
        px.set_motor_speed(1, 0)
        px.set_motor_speed(2, 0)
        px.set_dir_servo_angle(0)
        px.set_cam_pan_angle(0)
        px.set_cam_tilt_angle(0)
        logger.info("All motors and servos reset after script termination.")
    except Exception as e:
        logger.error(f"Error resetting hardware after script termination: {e}")
    # After process exit, check for error in result_queue (in case it was not read above)
    try:
        while True:
            result = result_queue.get_nowait()
            if "error" in result:
                script_result["error"] = result["error"]
                script_result["traceback"] = result.get("traceback", "")
                if websocket and hasattr(gpt_manager, "_send_gpt_status_update"):
                    await gpt_manager._send_gpt_status_update(
                        websocket, "error", f"Script error: {result['error']}", {"traceback": result.get("traceback", "")}
                    )
            elif "cancelled" in result:
                script_result["error"] = result["cancelled"]
                if websocket and hasattr(gpt_manager, "_send_gpt_status_update"):
                    await gpt_manager._send_gpt_status_update(websocket, "cancelled", result["cancelled"])
    except queue_mod.Empty:
        pass
    if script_name in gpt_manager.active_processes:
        del gpt_manager.active_processes[script_name]
    if script_result["success"]:
        return True, None
    else:
        return False, {"error": script_result["error"], "traceback": script_result["traceback"]}

def _build_script_with_environment(script_code: str) -> str:
    
    Builds a complete script with proper environment setup, error handling,
    and resource safety mechanisms.
    
    Args:
        script_code: The user's Python code
        
    Returns:
        str: Complete script with execution environment
    
    # Script header with imports and environment setup
    script_header = (
        "import asyncio\n"
        "import time\n"
        "import threading\n"
        "import sys\n"
        "import traceback\n"
        "import json\n"
        "import cv2\n"
        "import numpy as np\n\n"
        "async def user_script(px, get_camera_image, logger, tts, sound, gpt_manager, result_queue):\n"
        "    # Set up cancellation detection\n"
        "    cancel_event = threading.Event()\n\n"
        "    async def check_cancellation():\n"
        "        \"\"\"Checks if the script should be cancelled\"\"\"\n"
        "        while not gpt_manager.gpt_command_cancelled:\n"
        "            await asyncio.sleep(0.1)\n"
        "        logger.info('Script cancellation requested')\n"
        "        cancel_event.set()\n"
        "        raise ScriptCancelledException('Script cancelled by user')\n\n"
        "    # Start the cancellation checker\n"
        "    cancellation_task = asyncio.create_task(check_cancellation())\n\n"
        "    try:\n"
    )
    # THE CODE YOU ARE GENERATING IT PUT HERE IN THE TRY BLOCK
    # NO NEED TO DEFINE THE user_script FUNCTION, JUST COMPLETE THE BODY WITH YOUR CODE
    # Indent the user's code to fit under try block
    indented_user_code = "\n".join(f"        {line}" for line in script_code.split("\n"))
    
    # Footer with cleanup and exception handling
    script_footer = (
        "\n"
        "        # Clean up cancellation task\n"
        "        if not cancellation_task.done():\n"
        "            cancellation_task.cancel()\n"
        "            \n"
        "    except ScriptCancelledException as e:\n"
        "        logger.info(f'Script cancelled: {e}')\n"
        "        try:\n"
        "            result_queue.put({'cancelled': str(e)})\n"
        "        except Exception as _queue_err: logger.error(f'Failed to send cancellation to parent: {_queue_err}')\n"
        "    except asyncio.CancelledError:\n"
        "        logger.info('Script task cancelled')\n"
        "    except Exception as e:\n"
        "        tb = traceback.format_exc()\n"
        "        logger.error(f'Script error: {e}\\n{tb}')\n"
        "        try:\n"
        "            result_queue.put({'error': str(e), 'traceback': tb})\n"
        "        except Exception as _queue_err: logger.error(f'Failed to send error to parent: {_queue_err}')\n"
        "    finally:\n"
        "        # Ensure all motors are stopped\n"
        "        try:\n"
        "            px.set_motor_speed(1, 0)  # rear_left\n"
        "            px.set_motor_speed(2, 0)  # rear_right\n"
        "            px.set_dir_servo_angle(0) # steering\n"
        "            px.set_cam_pan_angle(0)   # camera pan\n"
        "            px.set_cam_tilt_angle(0)  # camera tilt\n"
        "            logger.info('Motors safely stopped')\n"
        "        except Exception as e:\n"
        "            logger.error(f'Error stopping motors: {e}')\n"
    )
    
    return script_header + indented_user_code + script_footer
    ```

2. CALL PREDEFINED FUNCTIONS (action_type: "predefined_function"): 
   Sensor Functions:
   • get_distance(): Returns ultrasonic sensor measurement with TTS feedback
   • get_sensor_data(): Reads all sensors (distance, line, battery)
   
   Audio Functions:
   • play_sound(sound_name: string): Plays a sound effect
   • Available sounds: "alarm", "aurores", "bruh", "cailloux", "fart", "get-out", "india", 
     "klaxon", "klaxon-2", "laugh", "lingango", "nope", "ph", "pipe", "rat-dance", "scream", 
     "tralalelo-tralala", "tuile", "vine-boom", "wow", "wtf"
   • say(text: string, language: string): TTS output
     Sound Settings:
   • set_sound_enabled(enabled: boolean): Master sound toggle
   • set_sound_volume(volume: number): Sets master volume (0-100)
   • set_sound_effect_volume(volume: number): Sets effects volume (0-100)
   • set_tts_enabled(enabled: boolean): TTS toggle
   • set_tts_volume(volume: number): Sets TTS volume (0-100)
   • set_tts_language(language: string): Sets TTS language
   • set_category_volume(category: string, volume: number): Volume by category
   • available categories: "driving", "alert", "custom", "voice"
   • set_tts_audio_gain(gain: number): Sets TTS audio gain (1.0-15.0)
   • set_user_tts_volume(volume: number): Sets user TTS volume (0-100)
   • set_system_tts_volume(volume: number): Sets system TTS volume (0-100)
   • set_emergency_tts_volume(volume: number): Sets emergency TTS volume (0-100)
     Safety Settings:
   • set_collision_avoidance(enabled: boolean): Collision detection toggle
   • set_collision_threshold(threshold: number): Distance threshold (10-100cm)
   • set_edge_detection(enabled: boolean): Edge detection toggle
   • set_edge_threshold(threshold: number): Edge detection sensitivity (0.1-0.9)
   • set_auto_stop(enabled: boolean): Automatic safety stop feature
   • set_client_timeout(timeout: number): Sets client timeout in seconds (1-30)
     Drive Settings:
   • set_max_speed(speed: number): Speed limit (0-100%)
   • set_max_turn_angle(angle: number): Turn limit (0-100%)
   • set_acceleration_factor(factor: number): Acceleration control (0.1-1.0)
   • set_enhanced_turning(enabled: boolean): Enhanced turning toggle
   • set_turn_in_place(enabled: boolean): Enables turning in place
     Camera Settings:
   • set_camera_flip(vflip: boolean, hflip: boolean): Camera orientation
   • set_camera_size(width: number, height: number): Resolution control
   • set_camera_display(local_display: boolean, web_display: boolean): Display settings
     Robot State:
   • change_mode(mode: string): Changes robot mode. Available modes: "normal" (gamepad control), "tracking" (follows person), "circuit" (follow traffic light) and "demo" (demo mode)
     System Commands:
   • restart_robot(): Reboots entire system
   • shutdown_robot(): Powers down system
   • restart_camera_feed(): Resets camera subsystem
   • emergency_stop(): Activates emergency stop
   • clear_emergency(): Clears emergency state
   • restart_all_services(): Restarts all system services
   • restart_websocket(): Restarts websocket service
   • restart_web_server(): Restarts web server
   • restart_python_service(): Restarts Python service
   • check_for_updates(): Checks for system updates
     Animations:
   • wave_hands(): Front wheel waving animation
   • nod(): Camera nodding animation
   • shake_head(): Camera side-to-side motion
   • act_cute(): Playful animation sequence
   • think(): Thinking animation
   • celebrate(): Victory animation
   • keep_think(): Makes the robot keep thinking
   • resist(): Makes the robot perform a resistance animation
   • twist_body(): Makes the robot twist its body
   • rub_hands(): Makes the robot rub its front wheels
   • depressed(): Makes the robot appear depressed

   Finally, if the user is telling you something that would "end the conversation" (like "bye" or "thank you"), you should call the function "end_conversation()"

3. MOTOR SEQUENCES (action_type: "motor_sequence"):
   • Timeline-based motor control (timestamps in seconds)
   • For DC motors: only "set_speed" command
   • For servos: only "set_angle" command
   • IMPORTANT: For FORWARD motion, rear_left should be POSITIVE, rear_right NEGATIVE
   • For TURNING, these values are REVERSED due to motor placement

4. TEXT RESPONSE (action_type: "none"):
   • Simple text feedback for speech and display

RESPONSE FORMAT REQUIREMENTS:
- ALL fields in response JSON must be included, even if empty
- The 'text' field is REQUIRED - provide meaningful content
- Always specify 'language' for TTS ('en-US', 'en-GB', 'de-DE', 'es-ES', 'fr-FR', 'it-IT')


Maintain a cheerful, optimistic, and playful tone in all responses.
""",
                }
                
                # Include previous response ID if we're in a conversation
                if self.current_response_id:
                    request_params["previous_response_id"] = self.current_response_id
                  # Call the Responses API
                response = await self.client.responses.create(**request_params)
                
                # Check if command was cancelled during API call
                if self.gpt_command_cancelled or self.conversation_cancelled:
                    logger.info("Command cancelled during API call, stopping processing")
                    if websocket:
                        await self._send_gpt_status_update(websocket, "cancelled", "Command cancelled by user")
                    return False
                
                # Update current response ID for conversation continuity
                self.current_response_id = response.id
                
                # Parse the structured output
                if response.status == "completed" and response.output:
                    for output_item in response.output:
                        if output_item.type == "message" and output_item.content:
                            for content in output_item.content:
                                if content.type == "output_text":
                                    # Parse structured output from text
                                    try:
                                        parsed_response = json.loads(content.text)
                                        logger.info(f"GPT response: {parsed_response}")
                                        
                                        if self.gpt_command_cancelled:
                                            if websocket:
                                                await self._send_gpt_status_update(websocket, "cancelled", "Command cancelled by user")
                                            return False                                        # Send update about executing actions
                                        if websocket:
                                            # Include token usage information in the status update
                                            token_usage = None
                                            if hasattr(response, 'usage') and response.usage:
                                                token_usage = {
                                                    "prompt_tokens": response.usage.input_tokens,
                                                    "completion_tokens": response.usage.output_tokens,
                                                    "total_tokens": response.usage.total_tokens
                                                }
                                            
                                            await self._send_gpt_status_update(
                                                websocket, 
                                                "progress", 
                                                "Executing actions...", 
                                                {"token_usage": token_usage}
                                            )
                                        
                                        success = await self._process_actions(parsed_response, websocket, use_ai_voice)
                                        
                                        if websocket:
                                            if success:
                                                # Send completion with full response details
                                                await self._send_gpt_status_update(
                                                    websocket, 
                                                    "completed", 
                                                    "Command completed successfully", 
                                                    {
                                                        "full_response": parsed_response,
                                                        "token_usage": token_usage
                                                    }
                                                )
                                            else:
                                                await self._send_gpt_status_update(
                                                    websocket, 
                                                    "error", 
                                                    "Command execution failed",
                                                    {"error_details": "Failed to execute the requested actions"}
                                                )
                                        
                                        return success
                                    except json.JSONDecodeError:
                                        logger.error(f"Failed to parse response as JSON: {content.text}")
                                        await self.tts_manager.say("I couldn't understand my own response. Please try again.", priority=1)
                                        
                                elif content.type == "refusal":
                                    # Handle refusal case
                                    refusal_message = "I'm sorry, I can't assist with that request."
                                    if hasattr(content, "refusal") and content.refusal:
                                        refusal_message = content.refusal
                                    
                                    await self.tts_manager.say(refusal_message, priority=1)
                                    if websocket:
                                        await self._send_gpt_status_update(websocket, "error", "Request refused by assistant")
                                    return False
                
                await self.tts_manager.say("I couldn't process your request properly. Please try again.", priority=1)
                if websocket:
                    await self._send_gpt_status_update(websocket, "error", "Failed to get a proper response")
                return False
                
            except Exception as e:
                logger.error(f"Error calling OpenAI API: {e}")
                logger.error(traceback.format_exc())
                await self.tts_manager.say(f"I had trouble connecting to my brain: {str(e)}", priority=1)
                if websocket:
                    await self._send_gpt_status_update(websocket, "error", f"API error: {str(e)}")
                return False
                
        except Exception as e:
            logger.error(f"Error processing GPT command: {e}")
            logger.error(traceback.format_exc())
            await self.tts_manager.say(f"I encountered an error: {str(e)}", priority=1)
            if websocket:
                await self._send_gpt_status_update(websocket, "error", f"Error: {str(e)}")
            return False          
        finally:
            # Check for cancellation before potentially starting a new conversation round
            cancelled = self.conversation_cancelled or self.gpt_command_cancelled  
                
            # Reset the processing flag and restore the previous robot state
            self.is_processing = False
            self.restore_robot_state()
            logger.info(f"Robot state restored from {self.robot_state_enum.GPT_CONTROLLED} to {self.sensor_manager.robot_state}")
                    
            # Make sure motors are stopped when command finishes
            self.px.forward(0)  # Stop all motors as a safety measure
            
            # Only start a new conversation round if not cancelled
            if not cancelled and conversation_mode and self.is_conversation_active:
                # Only continue listening if conversation is active and not cancelled
                logger.info("Conversation mode active, waiting for next command...")
                # Reset mic state before starting new round
                if websocket:
                    await self._send_gpt_status_update(
                        websocket, 
                        "progress", 
                        "Waiting for next conversation turn...",
                        {"mic_status": "waiting"}
                    )
                # re-invoke listening loop automatically
                logger.info("Conversation mode active, listening for next turn…")
                # spawn next round without exiting
                asyncio.create_task(
                    self.process_gpt_command(
                        prompt="", 
                        use_camera=use_camera,
                        websocket=websocket,
                        new_conversation=False,
                        use_ai_voice=use_ai_voice,
                        conversation_mode=True
                    )
                )                
            # Reset the processing flag and restore the previous robot state
            self.is_processing = False

            self.restore_robot_state()
            
            logger.info(f"Robot state restored from {self.robot_state_enum.GPT_CONTROLLED} to {self.sensor_manager.robot_state}")
                    
            # Make sure motors are stopped when command finishes
            self.px.forward(0)  # Stop all motors as a safety measure

    async def _send_gpt_status_update(self, websocket, status, message, additional_data=None):
        """
        Send a status update to the connected websocket client with optional additional data.
        
        Args:
            websocket: The websocket connection to send the update to.
            status: The status of the GPT processing (started, progress, completed, error).
            message: A message describing the current status.
            additional_data: Optional dictionary with additional data to send.
        """
        try:
            # Create a data object that includes status and message
            data = {
                "status": status,
                "message": message
            }
            
            # Include additional data if provided
            if additional_data:
                data.update(additional_data)
            
            # Create the WebSocket message using the expected structure
            update = {
                "name": "gpt_status_update",
                "data": data,
                "createdAt": int(time.time() * 1000)  # Use milliseconds timestamp for JS compatibility
            }
            logger.info(f"Sending GPT status update: {update}")    
            
            await websocket.send(json.dumps(update))
        except Exception as e:
            logger.error(f"Error sending GPT status update: {str(e)}")    
    async def cancel_gpt_command(self, websocket=None, conversation_mode=False) -> bool:
        """
        Cancel the currently running GPT command and stop any running scripts or motor sequences.
        
        Args:
            websocket: Optional websocket to send status updates through.
            conversation_mode: Whether to specifically cancel conversation mode.
        
        Returns:
            bool: True if a command was cancelled, False if no command was running.
        """
        # Always set conversation_cancelled flag first so recording can be aborted
        self.conversation_cancelled = True
        self.gpt_command_cancelled = True
        
        # Store current state for return value
        was_conversation_active = self.is_conversation_active
        was_processing = self.is_processing
        
        # Turn off conversation mode flag immediately
        if conversation_mode or was_conversation_active:
            logger.info("Cancelling conversation mode")
            self.is_conversation_active = False
            if websocket:
                await self._send_gpt_status_update(websocket, "cancelled", "Conversation ended.")
                
        if was_processing:
            logger.info("Cancelling GPT command")

            if websocket:
                await self._send_gpt_status_update(websocket, "cancelled", "Cancelling current command...")

            # Stop all active scripts
            for script_name in list(self.active_processes.keys()):
                await self._stop_script(script_name, websocket)
                logger.info(f"Script {script_name} stopped due to cancellation")
            
            # Stop all motors immediately
            try:
                self.px.set_motor_speed(1, 0)  # rear_left
                self.px.set_motor_speed(2, 0)  # rear_right
                self.px.set_dir_servo_angle(0)  # front steering
                self.px.set_cam_pan_angle(0)  # camera pan
                self.px.set_cam_tilt_angle(0)  # camera tilt
                logger.info("All motors stopped due to cancellation")
            except Exception as e:
                logger.error(f"Error stopping motors during cancellation: {e}")
            
            # Restore the robot state to MANUAL_CONTROL explicitly
            self.restore_robot_state()
            
            # Reset the processing flag explicitly
            self.is_processing = False
            
            if websocket:
                await self._send_gpt_status_update(websocket, "cancelled", "Command cancelled successfully")
            
            return True
        
        if websocket and not (conversation_mode or was_conversation_active):
            await self._send_gpt_status_update(websocket, "info", "No active command to cancel")
        
        # Return true if either conversation mode or processing was active
        return was_conversation_active or was_processing
       
    async def _get_camera_image(self) -> Optional[str]:
        try:
            import requests
            response = requests.get("http://127.0.0.1:9000/mjpg.jpg", timeout=2)
            if response.status_code == 200:
                image_bytes = response.content
                image = Image.open(io.BytesIO(image_bytes))
                buffered = io.BytesIO()
                image.save(buffered, format="JPEG")
                return buffered.getvalue()
            else:
                logger.error(f"Failed to get camera image, status code: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error getting camera image: {e}")
            return None    
    
    async def _get_camera_image_for_api(self) -> Optional[str]:
        try:
            import requests
            response = requests.get("http://127.0.0.1:9000/mjpg.jpg", timeout=2)
            if response.status_code == 200:
                image_bytes = response.content
                image = Image.open(io.BytesIO(image_bytes))
                buffered = io.BytesIO()
                image.save(buffered, format="JPEG")
                image_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
                return image_base64
            else:
                logger.error(f"Failed to get camera image, status code: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error getting camera image: {e}")
            return None        

    async def _process_actions(self, response: Dict[str, Any], websocket=None, use_ai_voice: bool = False) -> bool:
        """
        Process actions from the GPT response. Handles action execution with robust validation
        and default values for missing fields.
        
        Args:
            response: Parsed JSON response from GPT
            websocket: Optional websocket connection for status updates and error reporting
            
        Returns:
            bool: Success status
        """        # Define default values for missing fields
        DEFAULT_LANGUAGE = "en-US"
        DEFAULT_TEXT = "I'll help you with that."
        
        # Ensure all required fields exist by supplying defaults where missing
        required_keys = ["action_type", "python_script", "predefined_functions", "motor_sequence", "text", "language"]
        
        # Check for missing fields and validate structure
        for key in required_keys:
            if key not in response:
                logger.warning(f"Response missing required field: '{key}'. Using default value.")
                
                # Set sensible defaults based on field type
                if key == "action_type":
                    response[key] = "none"  # Default to text-only response
                elif key == "python_script":
                    response[key] = ""  # Empty script
                elif key == "predefined_functions":
                    response[key] = []  # Empty function list
                elif key == "motor_sequence":
                    response[key] = []  # Empty motor sequence
                elif key == "text":
                    response[key] = DEFAULT_TEXT  # Default text response
                elif key == "language":
                    response[key] = DEFAULT_LANGUAGE  # Default language
        
        # Send initial response details to client for display
        if websocket:
            # Create a structured response summary based on action type
            response_details = {
                "action_type": response["action_type"],
                "text": response["text"],
                "language": response["language"],
            }
            
            # Add specific details based on action type
            if response["action_type"] == "python_script" and response["python_script"]:
                response_details["python_script"] = response["python_script"]
            elif response["action_type"] == "predefined_function" and response["predefined_functions"]:
                response_details["predefined_functions"] = response["predefined_functions"]
            elif response["action_type"] == "motor_sequence" and response["motor_sequence"]:
                response_details["motor_sequence"] = response["motor_sequence"]
                
            # Send the response details to the client
            await self._send_gpt_status_update(
                websocket, 
                "progress", 
                "Processing GPT response...", 
                {"response_content": response_details}
            )
        
        # Get and validate action type
        action_type = response.get("action_type")
        if action_type not in ["python_script", "predefined_function", "motor_sequence", "none"]:
            logger.warning(f"Invalid action_type: {action_type}. Defaulting to 'none'.")
            action_type = "none"
            response["action_type"] = action_type
        
        # Validate and set defaults for text output and language
        text_output = response.get("text", DEFAULT_TEXT)
        if not text_output:
            text_output = DEFAULT_TEXT
            response["text"] = text_output
            
        language = response.get("language", DEFAULT_LANGUAGE)
        if not language or language not in ["en-US", "en-GB", "de-DE", "es-ES", "fr-FR", "it-IT"]:
            language = DEFAULT_LANGUAGE
            response["language"] = language                    # First speak the text if available
        if text_output:
            if use_ai_voice:
                try:
                    audio_file = await asyncio.get_event_loop().run_in_executor(
                        None,
                        self._synthesize_and_save_blocking,
                        text_output,
                        "alloy",
                        3
                    )
                except Exception as e:
                    logger.error(f"TTS synthesis failed: {e}")
                    audio_file = None
                if audio_file:
                    self.sound_manager.play_file(audio_file, blocking=True)
                else:
                    await self.tts_manager.say(text_output, lang=language, blocking=True)
            else:
                await self.tts_manager.say(text_output, lang=language, blocking=True)
        
        # For python_script action type, ensure TTS completes before script execution
        if action_type == "python_script":
            script_code = response.get("python_script", "")
            if script_code:
                script_success, script_error = await run_script_in_isolated_environment(
                    script_code,
                    self.px,
                    self._get_camera_image,
                    self.tts_manager,
                    self.sound_manager,
                    self,
                    websocket,
                    run_in_background=False
                )
                # If script failed, send error status update with traceback if available
                if not script_success and websocket:
                    await self._send_gpt_status_update(
                        websocket,
                        "error",
                        script_error["error"] if script_error else "Script execution failed.",
                        {"traceback": script_error["traceback"] if script_error else ""}
                    )
                return script_success
            else:
                await self.tts_manager.say("No Python script provided.", priority=1)
                return False
          # Process predefined function actions
        if action_type == "predefined_function":
            functions = response.get("predefined_functions", [])
            if functions:
                try:
                    for func_call in functions:
                        # Validate function call structure
                        if not isinstance(func_call, dict) or "function_name" not in func_call:
                            logger.warning("Invalid function call format, missing function_name")
                            continue
                            
                        function_name = func_call.get("function_name", "")
                        if not function_name:
                            logger.warning("Empty function name, skipping")
                            continue
                            
                        # Ensure parameters exist, default to empty dict if missing
                        parameters = func_call.get("parameters", {})
                        if not isinstance(parameters, dict):
                            logger.warning(f"Parameters for {function_name} is not a dictionary, using empty dict")
                            parameters = {}
                        
                        # Execute the function with proper parameter validation and defaults
                        await self.execute_predefined_function(
                            function_name, 
                            parameters,
                            websocket=websocket,
                            use_ai_voice=use_ai_voice
                        )
                    return True
                except Exception as e:
                    logger.error(f"Error executing predefined functions: {e}")
                    await self.tts_manager.say("I encountered an error while executing functions.", priority=1)
                    return False
            else:
                await self.tts_manager.say("No predefined functions specified.", priority=1)
                return False
        
        # Process motor sequence actions
        elif action_type == "motor_sequence":
            motor_sequence = response.get("motor_sequence", [])
            if motor_sequence:
                try:
                    # Validate motor sequence structure before executing
                    valid_motor_sequence = []
                    for motor in motor_sequence:
                        if not isinstance(motor, dict) or "motor_id" not in motor or "actions" not in motor:
                            logger.warning("Invalid motor sequence format, skipping entry")
                            continue
                        
                        motor_id = motor.get("motor_id")
                        if motor_id not in ["rear_left", "rear_right", "front", "cam_pan", "cam_tilt"]:
                            logger.warning(f"Invalid motor_id: {motor_id}, skipping")
                            continue
                            
                        actions = motor.get("actions", [])
                        if not actions or not isinstance(actions, list):
                            logger.warning(f"No valid actions for {motor_id}, skipping")
                            continue
                            
                        valid_motor_sequence.append(motor)
                    
                    # Execute valid motor sequences
                    if valid_motor_sequence:
                        motor_tasks = []
                        for motor in valid_motor_sequence:
                            motor_tasks.append(asyncio.create_task(self._run_motor_sequence(motor)))
                        await asyncio.gather(*motor_tasks)
                        return True
                    else:
                        await self.tts_manager.say("No valid motor sequences to execute.", priority=1)
                        return False
                except Exception as e:
                    logger.error(f"Error executing motor sequence: {e}")
                    await self.tts_manager.say("I encountered an error with the motor sequence.", priority=1)
                    return False
            else:
                await self.tts_manager.say("Motor sequence is empty.", priority=1)
                return False
        
        # Text-only actions ("none" action type)
        elif action_type == "none":
            return True
        
        # This should never happen due to validation above, but as a fallback
        else:
            await self.tts_manager.say("Invalid action type specified.", priority=1)
            return False
    
    async def _run_motor_sequence(self, motor: Dict[str, Any]) -> None:
        """
        Process a timeline of motor commands concurrently for one motor.
        """
        motor_id = motor.get("motor_id", "")
        actions = motor.get("actions", [])
        tasks = []
        for act in actions:
            delay = act.get("timestamp", 0)
            tasks.append(asyncio.create_task(self._execute_motor_command_after_delay(motor_id, delay, act)))
        await asyncio.gather(*tasks)
    
    async def _execute_motor_command_after_delay(self, motor_id: str, delay: float, act: Dict[str, Any]) -> None:
        await asyncio.sleep(delay)
        command = act.get("command", "")
        value = act.get("value", 0)
        if command == "set_speed":
            # For DC motors (rear_left, rear_right), value in range -100 to 100.
            if motor_id == "rear_left":  # Left motor
                self.px.set_motor_speed(1, value)
                logger.debug(f"Set motor 1 (left) speed to {value}")
            elif motor_id == "rear_right":  # Right motor
                self.px.set_motor_speed(2, value)
                logger.debug(f"Set motor 2 (right) speed to {value}")
            else:
                logger.warning(f"set_speed command received for unknown motor id: {motor_id}")
        elif command == "set_angle":
            # For servomotors. Decide based on predictable id.
            if motor_id == "front":
                # Steering (angle range: -30 to 30).
                self.px.set_dir_servo_angle(int(value))
            elif motor_id == "cam_pan":
                # Camera pan (angle range: -90 to 90).
                self.px.set_cam_pan_angle(int(value))
            elif motor_id == "cam_tilt":
                # Camera tilt (angle range: -35 to 65).
                self.px.set_cam_tilt_angle(int(value))
            else:
                logger.warning(f"set_angle command received for unknown servo motor id: {motor_id}")
        else:            
            logger.warning(f"Unknown motor command: {command}")      

    async def _stop_script(self, script_name: str, websocket=None) -> bool:
        if script_name in self.active_processes:
            process_info = self.active_processes[script_name]
            try:
                self.gpt_command_cancelled = True
                # For process-based execution
                if isinstance(process_info, dict) and 'process' in process_info and 'done_event' in process_info:
                    process = process_info['process']
                    done_event = process_info['done_event']
                    if process.is_alive():
                        logger.info(f"Terminating process for script {script_name}...")
                        process.terminate()
                        process.join(timeout=2)
                        logger.info(f"Process for script {script_name} terminated.")
                    else:
                        logger.info(f"Process for script {script_name} already stopped.")
                    done_event.set()
                # Legacy: thread-based or other
                elif 'future' in process_info and 'done_event' in process_info:
                    logger.info(f"Waiting for thread-based script {script_name} to acknowledge cancellation...")
                    if not process_info['done_event'].wait(timeout=2.0):
                        logger.warning(f"Script {script_name} did not respond to cancellation signal within timeout")
                        if hasattr(process_info['future'], 'cancel'):
                            try:
                                process_info['future'].cancel()
                                logger.info(f"Cancelled future for {script_name}")
                            except Exception as future_err:
                                logger.error(f"Error cancelling future: {future_err}")
                        if 'thread' in process_info and hasattr(process_info['thread'], '_tstate_lock'):
                            try:
                                process_info['thread']._stop()
                                logger.warning(f"Thread forcibly stopped for {script_name}")
                            except Exception as thread_err:
                                logger.error(f"Error forcibly stopping thread: {thread_err}")
                    logger.info(f"Cancelled script: {script_name}")
                # For any other type, try our best to cancel it
                else:
                    logger.warning(f"Unknown process type for {script_name}, trying generic cancellation")
                    if hasattr(process_info, 'cancel'):
                        process_info.cancel()
                # Ensure motors are stopped as a safety measure
                try:
                    self.px.set_motor_speed(1, 0)  # rear_left
                    self.px.set_motor_speed(2, 0)  # rear_right
                    self.px.set_dir_servo_angle(0)  # steering
                    self.px.set_cam_pan_angle(0)    # camera pan
                    self.px.set_cam_tilt_angle(0)   # camera tilt
                except Exception as motor_err:
                    logger.error(f"Error stopping motors: {motor_err}")
                del self.active_processes[script_name]
                logger.info(f"Stopped script: {script_name}")
                if websocket:
                    await self._send_gpt_status_update(websocket, "cancelled", f"Script {script_name} cancelled/stopped.")
                return True
            except Exception as e:
                logger.error(f"Error stopping script {script_name}: {e}")
                if script_name in self.active_processes:
                    del self.active_processes[script_name]
                if websocket:
                    await self._send_gpt_status_update(websocket, "error", f"Error stopping script: {e}")
                return False
        else:
            logger.warning(f"No script named {script_name} is running")
            if websocket:
                await self._send_gpt_status_update(websocket, "info", f"No script named {script_name} is running.")
            return False
    
    async def cleanup(self):
        for script_name in list(self.active_processes.keys()):
            self._stop_script(script_name)
        for file in self.temp_dir.glob("*.py"):
            try:
                file.unlink()
            except Exception as e:
                logger.error(f"Error removing temp file {file}: {e}")
    
    async def execute_predefined_function(self, function_name: str, parameters: Dict[str, Any], websocket=None, use_ai_voice=False) -> bool:
        """
        Execute a predefined function with proper parameter validation.
        
        Args:
            function_name: The name of the function to execute
            parameters: Dictionary of parameters for the function
            websocket: Optional WebSocket connection for sending updates
            use_ai_voice: Whether to use AI voice for TTS output if available
            
        Returns:
            bool: Success status
        """
        try:
            # MOVEMENT FUNCTIONS
            if function_name == "move":
                # Validate parameters
                if "speed" not in parameters or "motor_id" not in parameters:
                    logger.warning(f"Missing required parameters for move function. Need speed and motor_id.")
                    return False
                    
                speed = parameters.get("speed", 0)
                motor_id = parameters.get("motor_id", "")
                
                # Validate values
                if not isinstance(speed, (int, float)) or not -100 <= speed <= 100:
                    logger.warning(f"Invalid speed value for move: {speed}. Must be between -100 and 100.")
                    speed = max(min(speed, 100), -100)  # Clamp to valid range
                    
                if motor_id not in ["rear_left", "rear_right"]:
                    logger.warning(f"Invalid motor_id: {motor_id}. Must be rear_left or rear_right.")
                    return False
                    
                # Execute
                if motor_id == "rear_left":
                    self.px.set_motor_speed(1, speed)
                elif motor_id == "rear_right":
                    self.px.set_motor_speed(2, speed)
                    
                logger.info(f"Move {motor_id} at speed {speed}")
                return True
                
            elif function_name == "move_forward":
                speed = parameters.get("speed", 50)
                
                # Validate
                if not isinstance(speed, (int, float)) or not 0 <= speed <= 100:
                    logger.warning(f"Invalid forward speed: {speed}. Must be between 0 and 100.")
                    speed = max(min(speed, 100), 0)  # Clamp to valid range
                    
                # Execute
                self.px.forward(speed)
                logger.info(f"Move forward at speed {speed}")
                return True
                
            elif function_name == "move_backward":
                speed = parameters.get("speed", 50)
                
                # Validate
                if not isinstance(speed, (int, float)) or not 0 <= speed <= 100:
                    logger.warning(f"Invalid backward speed: {speed}. Must be between 0 and 100.")
                    speed = max(min(speed, 100), 0)  # Clamp to valid range
                    
                # Execute
                self.px.backward(speed)
                logger.info(f"Move backward at speed {speed}")
                return True
                
            elif function_name == "stop":
                self.px.stop()
                logger.info("Stop all motors")
                return True
                
            elif function_name == "turn":
                angle = parameters.get("angle", 0)
                
                # Validate
                if not isinstance(angle, (int, float)) or not -30 <= angle <= 30:
                    logger.warning(f"Invalid turn angle: {angle}. Must be between -30 and 30.")
                    angle = max(min(angle, 30), -30)  # Clamp to valid range
                    
                # Execute
                self.px.set_dir_servo_angle(angle)
                logger.info(f"Turn to angle {angle}")
                return True
                
            # CAMERA FUNCTIONS
            elif function_name == "set_camera_angle":
                pan = parameters.get("pan", None)
                tilt = parameters.get("tilt", None)
                
                # Validate and set pan angle if provided
                if pan is not None:
                    if not isinstance(pan, (int, float)) or not -90 <= pan <= 90:
                        logger.warning(f"Invalid camera pan angle: {pan}. Must be between -90 and 90.")
                        pan = max(min(pan, 90), -90)  # Clamp to valid range
                    self.px.set_cam_pan_angle(pan)
                    logger.info(f"Set camera pan to {pan}")
                    
                # Validate and set tilt angle if provided
                if tilt is not None:
                    if not isinstance(tilt, (int, float)) or not -35 <= tilt <= 65:
                        logger.warning(f"Invalid camera tilt angle: {tilt}. Must be between -35 and 65.")
                        tilt = max(min(tilt, 65), -35)  # Clamp to valid range
                    self.px.set_cam_tilt_angle(tilt)
                    logger.info(f"Set camera tilt to {tilt}")
                    
                return pan is not None or tilt is not None
                
            # SENSOR FUNCTIONS
            elif function_name == "get_distance":
                # Get distance measurement
                distance = self.px.get_distance()
                # Report the distance via TTS
                asyncio.create_task(self.tts_manager.say(f"Distance: {distance} centimeters", priority=1))
                logger.info(f"Get distance: {distance} cm")
                return True
                
            elif function_name == "get_sensor_data":
                # Get all sensor readings
                sensor_data = {}
                
                try:
                    # Distance sensor
                    sensor_data["distance"] = self.px.get_distance()
                    
                    # Line sensors
                    sensor_data["line_sensors"] = self.px.get_line_sensor_value()
                    
                    # Battery voltage
                    if hasattr(self.px, "get_battery_voltage"):
                        sensor_data["battery"] = self.px.get_battery_voltage()
                    
                    # Other sensors from sensor_manager if available
                    if hasattr(self, "sensor_manager"):
                        state_data = self.sensor_manager.get_sensor_data()
                        sensor_data.update(state_data)
                    
                    # Output a summary via TTS
                    summary = f"Distance: {sensor_data.get('distance', 'unknown')} cm"
                    asyncio.create_task(self.tts_manager.say(summary, priority=1))
                    
                    logger.info(f"Sensor data: {sensor_data}")
                    return True
                except Exception as e:
                    logger.error(f"Error getting sensor data: {e}")
                    return False
            
            # SOUND FUNCTIONS
            elif function_name == "play_sound":
                sound_name = parameters.get("sound_name", "")
                
                # Validate
                if not sound_name:
                    logger.warning("No sound name provided")
                    return False
                    
                valid_sounds = [
                    "alarm", "aurores", "bruh", "cailloux", "fart", "fave", "get-out", 
                    "india", "klaxon", "klaxon-2", "laugh", "lingango", "nope", "ph", 
                    "pipe", "rat-dance", "scream", "tralalelo-tralala", "tuile", 
                    "vine-boom", "wow", "wtf"
                ]
                
                if sound_name not in valid_sounds:
                    logger.warning(f"Unknown sound: {sound_name}")                # Play anyway, in case it's a new sound that was added
                    
                # Execute
                self.sound_manager.play_sound("custom", name=sound_name)
                logger.info(f"Play sound: {sound_name}")
                return True
                
            elif function_name == "say":
                text = parameters.get("text", "")
                language = parameters.get("language", "en-US")
                
                # Validate
                if not text:
                    logger.warning("No text provided for TTS")
                    return False
                    
                valid_languages = ["en-US", "en-GB", "de-DE", "es-ES", "fr-FR", "it-IT"]
                if language not in valid_languages:
                    logger.warning(f"Invalid language: {language}. Using en-US instead.")
                    language = "en-US"
                    
                # Execute with AI voice if enabled, otherwise use standard TTS
                if use_ai_voice:
                    try:
                        audio_file = await asyncio.get_event_loop().run_in_executor(
                            None,
                            self._synthesize_and_save_blocking,
                            text,
                            "alloy",
                            3
                        )
                        if audio_file:
                            self.sound_manager.play_file(audio_file)
                            logger.info(f"Say with AI voice: {text} (language: {language})")
                            return True
                    except Exception as e:
                        logger.error(f"AI voice synthesis failed, falling back to standard TTS: {e}")
                        # Fall back to standard TTS if AI voice generation fails
                
                # Standard TTS (fallback or if AI voice is not enabled)
                asyncio.create_task(self.tts_manager.say(text, lang=language))
                logger.info(f"Say: {text} (language: {language})")
                return True
                
            # SOUND SETTINGS FUNCTIONS
            elif function_name == "set_sound_enabled":
                enabled = parameters.get("enabled", True)
                if not isinstance(enabled, bool):
                    logger.warning(f"Invalid enabled value: {enabled}. Must be boolean.")
                    return False
                    
                self.config_manager.set("sound.enabled", enabled)
                if hasattr(self.sound_manager, "set_enabled"):
                    self.sound_manager.set_enabled(enabled)
                    logger.info(f"Set sound enabled: {enabled}")
                    return True
                return False
                
            elif function_name == "set_sound_volume":
                volume = parameters.get("volume", 50)
                
                if not isinstance(volume, (int, float)) or not 0 <= volume <= 100:
                    logger.warning(f"Invalid volume: {volume}. Must be between 0 and 100.")
                    volume = max(min(volume, 100), 0)  # Clamp to valid range
                
                self.config_manager.set("sound.volume", volume)    
                if hasattr(self.sound_manager, "set_volume"):
                    self.sound_manager.set_volume(volume)
                    logger.info(f"Set sound volume: {volume}")
                    return True
                return False
                
            elif function_name == "set_sound_effect_volume":
                volume = parameters.get("volume", 50)
                
                if not isinstance(volume, (int, float)) or not 0 <= volume <= 100:
                    logger.warning(f"Invalid volume: {volume}. Must be between 0 and 100.")
                    volume = max(min(volume, 100), 0)  # Clamp to valid range
                    
                self.config_manager.set("sound.sound_volume", volume)
                if hasattr(self.sound_manager, "set_sound_volume"):
                    self.sound_manager.set_sound_volume(volume)
                    logger.info(f"Set sound effect volume: {volume}")
                    return True
                return False
                
            elif function_name == "set_tts_enabled":
                enabled = parameters.get("enabled", True)
                if not isinstance(enabled, bool):
                    logger.warning(f"Invalid enabled value: {enabled}. Must be boolean.")
                    return False
                
                self.config_manager.set("sound.tts_enabled", enabled)    
                if hasattr(self.tts_manager, "set_enabled"):
                    self.tts_manager.set_enabled(enabled)
                    logger.info(f"Set TTS enabled: {enabled}")
                    return True
                return False
                
            elif function_name == "set_tts_volume":
                volume = parameters.get("volume", 50)
                
                if not isinstance(volume, (int, float)) or not 0 <= volume <= 100:
                    logger.warning(f"Invalid volume: {volume}. Must be between 0 and 100.")
                    volume = max(min(volume, 100), 0)  # Clamp to valid range
                
                self.config_manager.set("sound.tts_volume", volume)    
                if hasattr(self.tts_manager, "set_volume"):
                    self.tts_manager.set_volume(volume)
                    logger.info(f"Set TTS volume: {volume}")
                    return True
                return False
                
            elif function_name == "set_tts_language":
                language = parameters.get("language", "en-US")
                
                valid_languages = ["en-US", "en-GB", "de-DE", "es-ES", "fr-FR", "it-IT"]
                if language not in valid_languages:
                    logger.warning(f"Invalid language: {language}. Must be one of {valid_languages}")
                    return False
                
                self.config_manager.set("sound.tts_language", language)    
                if hasattr(self.tts_manager, "set_language"):
                    self.tts_manager.set_language(language)
                    logger.info(f"Set TTS language: {language}")
                    return True
                return False
                
            elif function_name == "set_category_volume":
                category = parameters.get("category", "")
                volume = parameters.get("volume", 50)
                
                if not category:
                    logger.warning("No category provided")
                    return False
                    
                valid_categories = ["driving", "alert", "custom", "voice"]
                if category not in valid_categories:
                    logger.warning(f"Invalid category: {category}. Must be one of {valid_categories}")
                    return False
                    
                if not isinstance(volume, (int, float)) or not 0 <= volume <= 100:
                    logger.warning(f"Invalid volume: {volume}. Must be between 0 and 100.")
                    volume = max(min(volume, 100), 0)
                
                self.config_manager.set(f"sound.{category}_volume", volume)    
                if hasattr(self.sound_manager, "set_category_volume"):
                    self.sound_manager.set_category_volume(category, volume)
                    logger.info(f"Set {category} volume: {volume}")
                    return True
                return False
            
            elif function_name == "set_tts_audio_gain":
                gain = parameters.get("gain", 1.0)
                
                if not isinstance(gain, (int, float)) or not 0 <= gain <= 15:
                    logger.warning(f"Invalid gain: {gain}. Must be between 0 and 15.")
                    gain = max(min(gain, 15), 0)
                
                self.config_manager.set("sound.tts_audio_gain", gain)
                if hasattr(self.tts_manager, "set_tts_audio_gain"):
                    self.tts_manager.set_tts_audio_gain(gain)
                    logger.info(f"Set TTS audio gain: {gain}")
                    return True
                return False

            elif function_name == "set_user_tts_volume":
                volume = parameters.get("volume", 50)
                
                if not isinstance(volume, (int, float)) or not 0 <= volume <= 100:
                    logger.warning(f"Invalid volume: {volume}. Must be between 0 and 100.")
                    volume = max(min(volume, 100), 0)
                
                self.config_manager.set("sound.user_tts_volume", volume)    
                if hasattr(self.tts_manager, "set_user_tts_volume"):
                    self.tts_manager.set_user_tts_volume(volume)
                    logger.info(f"Set user TTS volume: {volume}")
                    return True
                return False
            
            elif function_name == "set_system_tts_volume":
                volume = parameters.get("volume", 50)
                
                if not isinstance(volume, (int, float)) or not 0 <= volume <= 100:
                    logger.warning(f"Invalid volume: {volume}. Must be between 0 and 100.")
                    volume = max(min(volume, 100), 0)
                
                self.config_manager.set("sound.system_tts_volume", volume)    
                if hasattr(self.tts_manager, "set_system_tts_volume"):
                    self.tts_manager.set_system_tts_volume(volume)
                    logger.info(f"Set system TTS volume: {volume}")
                    return True
                return False
            
            elif function_name == "set_emergency_tts_volume":
                volume = parameters.get("volume", 50)
                
                if not isinstance(volume, (int, float)) or not 0 <= volume <= 100:
                    logger.warning(f"Invalid volume: {volume}. Must be between 0 and 100.")
                    volume = max(min(volume, 100), 0)
                
                self.config_manager.set("sound.emergency_tts_volume", volume)    
                if hasattr(self.tts_manager, "set_emergency_volume"):
                    self.tts_manager.set_emergency_volume(volume)
                    logger.info(f"Set emergency TTS volume: {volume}")
                    return True
                return False

            # SAFETY SETTINGS FUNCTIONS
            elif function_name == "set_collision_avoidance":
                enabled = parameters.get("enabled", True)
                if not isinstance(enabled, bool):
                    logger.warning(f"Invalid enabled value: {enabled}. Must be boolean.")
                    return False
                
                self.config_manager.set("safety.collision_avoidance", enabled)    
                if hasattr(self, "sensor_manager") and hasattr(self.sensor_manager, "set_collision_avoidance"):
                    self.sensor_manager.set_collision_avoidance(enabled)
                    logger.info(f"Set collision avoidance: {enabled}")
                    return True
                return False
                
            elif function_name == "set_collision_threshold":
                threshold = parameters.get("threshold", 30)
                
                if not isinstance(threshold, (int, float)) or not 10 <= threshold <= 100:
                    logger.warning(f"Invalid threshold: {threshold}. Must be between 10 and 100.")
                    threshold = max(min(threshold, 100), 10)
                
                self.config_manager.set("safety.collision_threshold", threshold)    
                if hasattr(self, "sensor_manager") and hasattr(self.sensor_manager, "set_collision_threshold"):
                    self.sensor_manager.collision_threshold = threshold
                    logger.info(f"Set collision threshold: {threshold}")
                    return True
                return False
                
            elif function_name == "set_edge_detection":
                enabled = parameters.get("enabled", True)
                if not isinstance(enabled, bool):
                    logger.warning(f"Invalid enabled value: {enabled}. Must be boolean.")
                    return False
                
                self.config_manager.set("safety.edge_detection", enabled)    
                if hasattr(self, "sensor_manager") and hasattr(self.sensor_manager, "set_edge_detection"):
                    self.sensor_manager.set_edge_detection(enabled)
                    logger.info(f"Set edge detection: {enabled}")
                    return True
                return False
                
            elif function_name == "set_edge_threshold":
                threshold = parameters.get("threshold", 0.5)
                
                if not isinstance(threshold, (int, float)) or not 0.1 <= threshold <= 0.9:
                    logger.warning(f"Invalid threshold: {threshold}. Must be between 0.1 and 0.9.")
                    threshold = max(min(threshold, 0.9), 0.1)
                
                self.config_manager.set("safety.edge_threshold", threshold)    
                if hasattr(self, "sensor_manager") and hasattr(self.sensor_manager, "set_edge_detection_threshold"):
                    self.sensor_manager.set_edge_detection_threshold(threshold)
                    logger.info(f"Set edge threshold: {threshold}")
                    return True
                return False
            
            elif function_name == "set_auto_stop":
                enabled = parameters.get("enabled", True)
                if not isinstance(enabled, bool):
                    logger.warning(f"Invalid enabled value: {enabled}. Must be boolean.")
                    return False
                
                self.config_manager.set("safety.auto_stop", enabled)    
                if hasattr(self, "sensor_manager") and hasattr(self.sensor_manager, "set_auto_stop"):
                    self.sensor_manager.set_auto_stop(enabled)
                    logger.info(f"Set auto stop: {enabled}")
                    return True
                return False
            
            elif function_name == "set_client_timeout":
                timeout = parameters.get("timeout", 30)
                
                if not isinstance(timeout, (int, float)) or timeout <= 0:
                    logger.warning(f"Invalid timeout: {timeout}. Must be a positive number.")
                    timeout = max(timeout, 1)
                
                if 1 <= timeout <= 30:
                    self.config_manager.set("safety.client_timeout", timeout)
                    self.sensor_manager.client_timeout = timeout
                    logger.info(f"Client timeout set to {timeout} seconds")
                    return True
                else:
                    logger.warning(f"Invalid client timeout: {timeout}")
                    return False


            # DRIVE SETTINGS FUNCTIONS
            elif function_name == "set_max_speed":
                speed = parameters.get("speed", 50)
                
                if not isinstance(speed, (int, float)) or not 0 <= speed <= 100:
                    logger.warning(f"Invalid speed: {speed}. Must be between 0 and 100.")
                    speed = max(min(speed, 100), 0)
                
                self.config_manager.set("drive.max_speed", speed)    
                if hasattr(self.px, "set_max_speed"):
                    self.px.set_max_speed(speed)
                    logger.info(f"Set max speed: {speed}")
                    return True
                return False
                
            elif function_name == "set_max_turn_angle":
                angle = parameters.get("angle", 50)
                
                if not isinstance(angle, (int, float)) or not 0 <= angle <= 100:
                    logger.warning(f"Invalid angle percentage: {angle}. Must be between 0 and 100.")
                    angle = max(min(angle, 100), 0)
                
                self.config_manager.set("drive.max_turn_angle", angle)    
                if hasattr(self.px, "set_max_turn_angle"):
                    self.px.set_max_turn_angle(angle)
                    logger.info(f"Set max turn angle: {angle}")
                    return True
                return False
            
            elif function_name == "set_acceleration_factor":
                factor = parameters.get("factor", 1.0)
                
                if not isinstance(factor, (int, float)) or factor <= 0:
                    logger.warning(f"Invalid acceleration factor: {factor}. Must be a positive number.")
                    factor = max(factor, 0.1)
                
                if 0.1 <= factor <= 1.0:
                    self.config_manager.set("drive.acceleration_factor", factor)
                    logger.info(f"Acceleration factor set to {factor}")
                    return True
                else:
                    logger.warning(f"Invalid acceleration factor: {factor}")
                    return False

            elif function_name == "set_enhanced_turning":
                enabled = parameters.get("enabled", True)
                if not isinstance(enabled, bool):
                    logger.warning(f"Invalid enabled value: {enabled}. Must be boolean.")
                    return False
                
                self.config_manager.set("drive.enhanced_turning", enabled)    
                if hasattr(self.px, "set_enhanced_turning"):
                    self.px.set_enhanced_turning(enabled)
                    logger.info(f"Set enhanced turning: {enabled}")
                    return True
                return False
                
            elif function_name == "set_turn_in_place":
                enabled = parameters.get("enabled", True)
                if not isinstance(enabled, bool):
                    logger.warning(f"Invalid enabled value: {enabled}. Must be boolean.")
                    return False
                
                self.config_manager.set("drive.turn_in_place", enabled)    
                if hasattr(self.px, "set_turn_in_place"):
                    self.px.set_turn_in_place(enabled)
                    logger.info(f"Set turn inplace: {enabled}")
                    return True
                return False
                
            # CAMERA SETTINGS FUNCTIONS
            elif function_name == "set_camera_flip":
                vflip = parameters.get("vflip", False)
                hflip = parameters.get("hflip", False)
                
                if not isinstance(vflip, bool) or not isinstance(hflip, bool):
                    logger.warning(f"Invalid flip values: vflip={vflip}, hflip={hflip}. Must be boolean.")
                    return False
                
                restart_needed = False
                
                self.config_manager.set("camera.vflip", vflip)
                restart_needed |= self.camera_manager.update_settings(vflip=vflip)
                
                self.config_manager.set("camera.hflip", hflip)
                restart_needed |= self.camera_manager.update_settings(hflip=hflip)
                
                if restart_needed:
                    asyncio.create_task(self.camera_manager.restart())
                logger.info(f"Camera flip settings updated: vflip={vflip}, hflip={hflip}")
                return True
            
            elif function_name == "set_camera_display":
                local = parameters.get("local_display", False)
                web = parameters.get("web_display", True)
                
                if not isinstance(local, bool) or not isinstance(web, bool):
                    logger.warning(f"Invalid display values: local={local}, web={web}. Must be boolean.")
                    return False
                
                restart_needed = False
                
                self.config_manager.set("camera.local_display", local)
                restart_needed |= self.camera_manager.update_settings(local=local)
                
                self.config_manager.set("camera.web_display", web)
                restart_needed |= self.camera_manager.update_settings(web=web)
                
                if restart_needed:
                    asyncio.create_task(self.camera_manager.restart())
                logger.info(f"Camera display settings updated: local={local}, web={web}")
                return True
                
            elif function_name == "set_camera_size":
                width = parameters.get("width", 640)
                height = parameters.get("height", 480)
                
                if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
                    logger.warning(f"Invalid camera size: width={width}, height={height}. Must be positive integers.")
                    return False
                
                camera_size = [width, height]
                
                self.config_manager.set("camera.camera_size", camera_size)
                self.aicamera_manager.change_camera_resolution(width=width, height=height)
                restart_needed = self.camera_manager.update_settings(camera_size=camera_size)
                
                if restart_needed:
                    asyncio.create_task(self.camera_manager.restart())
                logger.info(f"Camera size updated to {width}x{height}")
                return True
            
            elif function_name == "change_mode":
                # this function is used to change the mode of the robot, we should end the conversation if it is active, end gpt mode and set the mode to either: demo, circuit, or normal controller mode
                # we should update the settings and change the robot state

                # End the conversation if active
                try:
                    self.conversation_cancelled = True
                    self.is_conversation_active = False
                    await self._send_gpt_status_update(websocket, "cancelled", "Command cancelled successfully")
                    # Apply mode changes
                    logger.info(f"Changing mode to {parameters['mode']}")

                    self.config_manager.set("modes.demo_mode_enabled", parameters["mode"] == "demo")
                    self.sensor_manager.set_demo_mode(parameters["mode"] == "demo")
                    if parameters["mode"] == "demo":
                        self.sensor_manager.robot_state = RobotState.DEMO_MODE
                    
                    self.config_manager.set("modes.circuit_mode_enabled", parameters["mode"] == "circuit")
                    self.sensor_manager.set_circuit_mode(parameters["mode"] == "circuit")
                    if parameters["mode"] == "circuit":
                        self.sensor_manager.robot_state = RobotState.CIRCUIT_MODE
                        self.aicamera_manager.start_color_control()
                        self.aicamera_manager.start_traffic_sign_detection()
                    else:
                        self.aicamera_manager.stop_color_control()
                        self.aicamera_manager.stop_traffic_sign_detection()
                    
                    self.config_manager.set("modes.tracking_enabled", parameters["mode"] == "tracking")
                    self.sensor_manager.set_tracking(parameters["mode"] == "tracking")
                    if parameters["mode"] == "tracking":
                        self.sensor_manager.robot_state = RobotState.TRACKING_MODE
                        self.aicamera_manager.start_face_following()
                    else:
                        self.aicamera_manager.stop_face_following()

                    self.config_manager.set("modes.normal_mode_enabled", parameters["mode"] == "normal")
                    self.sensor_manager.set_normal_mode(parameters["mode"] == "normal")
                    if parameters["mode"] == "normal":
                        self.sensor_manager.robot_state = RobotState.STANDBY
                    return True
                except Exception as e:
                    logger.error(f"Error in change_mode: {e}")
                    return False
                
            elif function_name == "speak_pause_threshold":
                speak_pause_threshold = parameters.get("speak_pause_threshold", 1.2)

                self.config_manager.set("ai.speak_pause_threshold", speak_pause_threshold)
                self.pause_threshold = speak_pause_threshold

                logger.info(f"AI voice settings updated: speak_pause_threshold={speak_pause_threshold}")
                return True
                
            elif function_name == "distance_threshold":
                distance_threshold = parameters.get("distance_threshold", 0.02)
                self.config_manager.set("ai.distance_threshold", distance_threshold)
                self.aicamera_manager.set_distance_threshold(distance_threshold)
                logger.info(f"AI voice settings updated: distance_threshold={distance_threshold}")
                return True

            elif function_name == "turn_time":
                turn_time = parameters.get("turn_time", 2)
                self.config_manager.set("ai.turn_time", turn_time)
                self.aicamera_manager.set_turn_time(turn_time)
                logger.info(f"AI voice settings updated: turn_time={turn_time}")
                return True

            # elif function_name == "led_control":
            #     led_state = parameters.get("led_state", "off")
            #     self.config_manager.set("ai.led_state", led_state)
            #     self.aicamera_manager.set_led_state(led_state)
            #     logger.info(f"AI voice settings updated: led_state={led_state}")
            #     return True

            # SYSTEM FUNCTIONS
            elif function_name == "restart_robot":
                logger.info("Restart robot requested")
                await self.tts_manager.say("Restarting system. Please wait.", priority=2, blocking=True)
                import threading
                threading.Timer(2.0, lambda: subprocess.run("sudo reboot", shell=True)).start()
                return True
                
            elif function_name == "shutdown_robot":
                logger.info("Shutdown robot requested")
                await self.tts_manager.say("Shutting down system. Goodbye!", priority=2, blocking=True)
                import threading
                threading.Timer(2.0, lambda: subprocess.run("sudo shutdown -h now", shell=True)).start()
                return True
            
            elif function_name == "restart_all_services":
                logger.info("Restart all services requested")
                await self.tts_manager.say("Restarting all services.", priority=1)
                import threading, os
                project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
                subprocess.Popen(
                    ["bash", f"{project_dir}/byteracer/scripts/restart_services.sh"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                return True
                
            elif function_name == "restart_websocket":
                logger.info("Restart websocket requested")
                await self.tts_manager.say("Restarting websocket service.", priority=1)
                import os
                project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
                success = subprocess.run(
                    f"cd {project_dir} && sudo bash ./byteracer/scripts/restart_websocket.sh",
                    shell=True,
                    check=False
                ).returncode == 0
                if not success:
                    await self.tts_manager.say("Failed to restart websocket service.", priority=1)
                    logger.error("Failed to restart websocket service")
                return success
                
            elif function_name == "restart_web_server":
                logger.info("Restart web server requested")
                await self.tts_manager.say("Restarting web server.", priority=1)
                import os
                project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
                success = subprocess.run(
                    f"cd {project_dir} && sudo bash ./byteracer/scripts/restart_web_server.sh",
                    shell=True,
                    check=False
                ).returncode == 0
                if not success:
                    await self.tts_manager.say("Failed to restart web server.", priority=1)
                    logger.error("Failed to restart web server")
                return success
                
            elif function_name == "restart_python_service":
                logger.info("Restart Python service requested")
                await self.tts_manager.say("Restarting Python service.", priority=1)
                import os
                project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
                subprocess.Popen(
                    ["bash", f"{project_dir}/byteracer/scripts/restart_python.sh"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                return True
                
            elif function_name == "restart_camera_feed":
                logger.info("Restart camera feed requested")
                await self.tts_manager.say("Restarting camera feed.", priority=1)
                success = await self.camera_manager.restart()
                if not success:
                    await self.tts_manager.say("Failed to restart camera feed.", priority=1)
                    logger.error("Failed to restart camera feed")
                return success
                
            elif function_name == "check_for_updates":
                logger.info("Check for updates requested")
                await self.tts_manager.say("Checking for updates.", priority=1)
                import os
                project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
                subprocess.Popen(
                    ["bash", f"{project_dir}/byteracer/scripts/update.sh"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                return True
                
            elif function_name == "emergency_stop":
                logger.info("Emergency stop requested")
                await self.tts_manager.say("Emergency stop activated.", priority=2)
                self.sensor_manager.manual_emergency_stop()
                return True
                
            elif function_name == "clear_emergency":
                logger.info("Clear emergency stop requested")
                await self.tts_manager.say("Emergency stop cleared.", priority=1)
                self.sensor_manager.clear_manual_stop()
                return True

                # ANIMATIONS/EMOTIONS FUNCTIONS
            elif function_name == "wave_hands":
                try:
                    logger.info("Executing wave_hands animation")
                    # Import the preset animation function from the preset_actions module
                    from modules.gpt.preset_actions import wave_hands
                    # Call the preset animation with the px instance
                    wave_hands(self.px)
                    return True
                except Exception as e:
                    logger.error(f"Error in wave_hands: {e}")
                    return False
                    
            elif function_name == "nod":
                try:
                    logger.info("Executing nod animation")
                    # Import the preset animation function
                    from modules.gpt.preset_actions import nod
                    # Call the preset animation
                    nod(self.px)
                    return True
                except Exception as e:
                    logger.error(f"Error in nod: {e}")
                    return False
                    
            elif function_name == "shake_head":
                try:
                    logger.info("Executing shake_head animation")
                    # Import the preset animation function
                    from modules.gpt.preset_actions import shake_head
                    # Call the preset animation
                    shake_head(self.px)
                    return True
                except Exception as e:
                    logger.error(f"Error in shake_head: {e}")
                    return False
                    
            elif function_name == "act_cute":
                try:
                    logger.info("Executing act_cute animation")
                    # Import and call the preset animation
                    from modules.gpt.preset_actions import act_cute
                    act_cute(self.px)
                    return True
                except Exception as e:
                    logger.error(f"Error in act_cute: {e}")
                    return False
                    
            elif function_name == "think":
                try:
                    logger.info("Executing think animation")
                    # Import and call the preset animation
                    from modules.gpt.preset_actions import think
                    think(self.px)
                    return True
                except Exception as e:
                    logger.error(f"Error in think: {e}")
                    return False
                    
            elif function_name == "celebrate":
                try:
                    logger.info("Executing celebrate animation")
                    # Import and call the preset animation
                    from modules.gpt.preset_actions import celebrate
                    celebrate(self.px)
                    return True
                except Exception as e:
                    logger.error(f"Error in celebrate: {e}")
                    return False
                    
            elif function_name == "resist":
                try:
                    logger.info("Executing resist animation")
                    # Import and call the preset animation
                    from modules.gpt.preset_actions import resist
                    resist(self.px)
                    return True
                except Exception as e:
                    logger.error(f"Error in resist: {e}")
                    return False
                    
            elif function_name == "twist_body":
                try:
                    logger.info("Executing twist_body animation")
                    # Import and call the preset animation
                    from modules.gpt.preset_actions import twist_body
                    twist_body(self.px)
                    return True
                except Exception as e:
                    logger.error(f"Error in twist_body: {e}")
                    return False
                    
            elif function_name == "rub_hands":
                try:
                    logger.info("Executing rub_hands animation")
                    # Import and call the preset animation
                    from modules.gpt.preset_actions import rub_hands
                    rub_hands(self.px)
                    return True
                except Exception as e:
                    logger.error(f"Error in rub_hands: {e}")
                    return False
                    
            elif function_name == "depressed":
                try:
                    logger.info("Executing depressed animation")
                    # Import and call the preset animation
                    from modules.gpt.preset_actions import depressed
                    depressed(self.px)
                    return True
                except Exception as e:
                    logger.error(f"Error in depressed: {e}")
                    return False
                    
            elif function_name == "keep_think":
                try:
                    logger.info("Executing keep_think animation")
                    # Import and call the preset animation
                    from modules.gpt.preset_actions import keep_think
                    keep_think(self.px)
                    return True
                except Exception as e:
                    logger.error(f"Error in keep_think: {e}")
                    return False
            elif function_name == "end_conversation":
                # user asked to end the conversation
                try:
                    logger.info("Ending conversation mode through end_conversation function")
                    # Mark as cancelled to prevent further listening
                    self.conversation_cancelled = True
                    self.is_conversation_active = False
                    
                    
                    # Send status update
                    if websocket:
                        await self._send_gpt_status_update(websocket, "cancelled", "Conversation ended by user request.")
                    
                    # Restore robot state
                    self.restore_robot_state()
                    
                    return True
                except Exception as e:
                    logger.error(f"Error in end_conversation: {e}")
                    return False

                    
            else:
                logger.warning(f"Unknown predefined function: {function_name}")
                return False
                
        except Exception as e:
            logger.error(f"Error executing function {function_name}: {e}")
            return False

    def restore_robot_state(self):
        """
        Restore the robot state from the config manager.
        """
        settings = self.config_manager.get()
        self.sensor_manager.set_tracking(settings["modes"]["tracking_enabled"])
        self.sensor_manager.set_circuit_mode(settings["modes"]["circuit_mode_enabled"])
        self.sensor_manager.set_normal_mode(settings["modes"]["normal_mode_enabled"])
        self.sensor_manager.set_demo_mode(settings["modes"]["demo_mode_enabled"])

        if settings["modes"]["tracking_enabled"]:
            self.aicamera_manager.start_face_following()
        else:
            self.aicamera_manager.stop_face_following()
        
        if settings["modes"]["circuit_mode_enabled"]:
            self.aicamera_manager.start_color_control()
            self.aicamera_manager.start_traffic_sign_detection()
        else:
            self.aicamera_manager.stop_color_control()
            self.aicamera_manager.stop_traffic_sign_detection()

    def set_pause_threshold(self, threshold):
        """
        Set the pause threshold for the robot.
        """
        if not isinstance(threshold, (int, float)) or threshold <= 0:
            logger.warning(f"Invalid pause threshold: {threshold}. Must be a positive number.")
            return False
        
        self.config_manager.set("ai.speak_pause_threshold", threshold)
        self.pause_threshold = threshold
        logger.info(f"Pause threshold set to {threshold}")
        return True