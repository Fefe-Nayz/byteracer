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
    
    def __init__(self, px, camera_manager, tts_manager, sound_manager, sensor_manager, config_manager):
        """
        Initialize the GPT manager with references to other system components.
        
        Args:
            px: Picarx instance for hardware control.
            camera_manager: Manager for accessing the camera feed.
            tts_manager: TTS manager for text-to-speech output.
            sound_manager: Sound manager for audio playback.
            sensor_manager: Sensor manager for accessing robot sensors.
            config_manager: Configuration manager for accessing settings.
        """
        self.px = px
        self.camera_manager = camera_manager
        self.tts_manager = tts_manager
        self.sound_manager = sound_manager
        self.sensor_manager = sensor_manager
        self.config_manager = config_manager

        self.robot_state_enum = RobotState
        
        api_settings = self.config_manager.get("api")
        self.api_key = os.environ.get("OPENAI_API_KEY") or api_settings.get("openai_api_key", "")
        self.model = api_settings.get("model", "gpt-4o")
        
        if not self.api_key:
            logger.warning("OPENAI_API_KEY not found in environment variables or settings")
        
        # Configure OpenAI client
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url="https://api.openai.com/v1"
        )
        
        self.temp_dir = Path(tempfile.gettempdir()) / "byteracer_scripts"
        os.makedirs(self.temp_dir, exist_ok=True)
        logger.info(f"Using temporary directory for scripts: {self.temp_dir}")
        
        self.active_processes = {}
        self.is_processing = False
        self.gpt_command_cancelled = False
        self.current_response_id = None
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
                await self._send_gpt_status_update(websocket, "completed", "Created new conversation thread.")
            
            return True
        except Exception as e:
            logger.error(f"Error creating new conversation: {e}")
            if websocket:
                await self._send_gpt_status_update(websocket, "error", f"Failed to create new conversation: {str(e)}")
            return False
    async def process_gpt_command(self, prompt: str, use_camera: bool = False, websocket = None, new_conversation=False, robot_state=None) -> bool:
        """
        Process a GPT command with optional camera feed inclusion.
        
        Args:
            prompt: The natural language command from the user.
            use_camera: Whether to include the camera feed.
            websocket: Optional websocket connection for status updates.
            new_conversation: Whether to start a new conversation (reset thread).
            
        Returns:
            bool: Success status.
        """
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

            old_state = robot_state if robot_state is not None else self.robot_state_enum.STANDBY
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
                    image_data = await self._get_camera_image()
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
"parameters": {              "type": "object",
              "description": "A JSON object containing the parameters for the function.",
              "properties": {
                "motor_id": {"type": "string", "description": "ID of the motor to control"},
                "speed": {"type": "number", "description": "Speed value (-100 to 100)"},
                "angle": {"type": "number", "description": "Angle value for servos"},
                "pan": {"type": "number", "description": "Camera pan angle (-90 to 90)"},
                "tilt": {"type": "number", "description": "Camera tilt angle (-35 to 65)"},
                "text": {"type": "string", "description": "Text for TTS output"},
                "language": {"type": "string", "description": "Language code for TTS"},
                "sound_name": {"type": "string", "description": "Name of sound to play"},
                "volume": {"type": "number", "description": "Volume level (0-100)"},
                "enabled": {"type": "boolean", "description": "Enable/disable flag"},
                "threshold": {"type": "number", "description": "Threshold value for sensors"},
                "factor": {"type": "number", "description": "Factor value for calculations"},
                "priority": {"type": "number", "description": "Priority level for operations"},
                "timeout": {"type": "number", "description": "Timeout value in seconds"},
                "gain": {"type": "number", "description": "Gain value for audio"},
                "category": {"type": "string", "description": "Category name"},
                "vflip": {"type": "boolean", "description": "Vertical flip for camera"},
                "hflip": {"type": "boolean", "description": "Horizontal flip for camera"},
                "width": {"type": "number", "description": "Width dimension"},
                "height": {"type": "number", "description": "Height dimension"},
                "local_display": {"type": "boolean", "description": "Local display setting"},
                "web_display": {"type": "boolean", "description": "Web display setting"}
              },
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
   
   The `px` object provides these methods to control the robot:
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
   • get_camera_image(): Returns base64 encoded image data from camera
   
   For text-to-speech (always use await):
   • await tts.say("Your message", priority=1, lang="en-US"): Speaks message
     - priority: 1=high, 2=medium, 3=low
     - lang: "en-US", "en-GB", "de-DE", "es-ES", "fr-FR", "it-IT"
   
   For sound effects:
   • sound.play_sound("sound_name"): Plays a specific sound effect
     - Available sounds: "alarm", "aurores", "bruh", etc. (see full list above)
   
   For timing (always use await for sleep):
   • await asyncio.sleep(seconds): Asynchronous sleep, pauses execution
   • DO NOT use time.sleep() in scripts - it blocks the event loop

2. CALL PREDEFINED FUNCTIONS (action_type: "predefined_function"):
   Movement Functions:
   • move(motor_id: string, speed: number): Controls individual motors (-100 to 100%)
   • move_forward(speed: number): Moves robot forward (0 to 100%)
   • move_backward(speed: number): Moves robot backward (0 to 100%)
   • stop(): Immediately stops all motors
   • turn(angle: number): Sets steering angle (-30 to 30 degrees)

   Camera Functions:
   • set_camera_angle(pan: number, tilt: number): Sets camera position
   
   Sensor Functions:
   • get_distance(): Returns ultrasonic sensor measurement with TTS feedback
   • get_sensor_data(): Reads all sensors (distance, line, battery)
   
   Audio Functions:
   • say(text: string, language: string): Uses TTS to speak
   • play_sound(sound_name: string): Plays a sound effect
   • Available sounds: "alarm", "aurores", "bruh", "cailloux", "fart", "get-out", "india", 
     "klaxon", "klaxon-2", "laugh", "lingango", "nope", "ph", "pipe", "rat-dance", "scream", 
     "tralalelo-tralala", "tuile", "vine-boom", "wow", "wtf"
     Sound Settings:
   • set_sound_enabled(enabled: boolean): Master sound toggle
   • set_sound_volume(volume: number): Sets master volume (0-100)
   • set_sound_effect_volume(volume: number): Sets effects volume (0-100)
   • set_tts_enabled(enabled: boolean): TTS toggle
   • set_tts_volume(volume: number): Sets TTS volume (0-100)
   • set_tts_language(language: string): Sets TTS language
   • set_category_volume(category: string, volume: number): Volume by category
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

3. MOTOR SEQUENCES (action_type: "motor_sequence"):
   • Timeline-based motor control (timestamps in seconds)
   • For DC motors: only "set_speed" command
   • For servos: only "set_angle" command
   • IMPORTANT: For FORWARD motion, rear_left should be POSITIVE, rear_right NEGATIVE
   • For TURNING, these values are REVERSED due to motor placement

4. TEXT RESPONSE (action_type: "none"):
   • Simple text feedback for speech and display

SCRIPT EXECUTION GUIDELINES:
- Always validate image data before processing
- Handle potential None returns from get_camera_image()
- Use proper async/await patterns with asyncio
- Use await asyncio.sleep() not time.sleep() for waiting
- Always include proper error handling

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
                                                    "prompt_tokens": response.usage.prompt_tokens,
                                                    "completion_tokens": response.usage.completion_tokens,
                                                    "total_tokens": response.usage.total_tokens
                                                }
                                            
                                            await self._send_gpt_status_update(
                                                websocket, 
                                                "progress", 
                                                "Executing actions...", 
                                                {"token_usage": token_usage}
                                            )
                                        
                                        success = await self._process_actions(parsed_response, websocket)
                                        
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
            # Reset the processing flag and restore the previous robot state
            self.is_processing = False
            if old_state != self.robot_state_enum.STANDBY:
                # Only restore to previous state if it wasn't the waiting state
                self.sensor_manager.robot_state = old_state
            else:
                # If previous state was waiting, set to client controlled
                self.sensor_manager.robot_state = self.robot_state_enum.MANUAL_CONTROL
            
            logger.info(f"Robot state restored from {self.robot_state_enum.GPT_CONTROLLED} to {self.sensor_manager.robot_state}")
                    
            # Make sure motors are stopped when command finishes
            self.px.forward(0)  # Stop all motors as a safety measure

    async def _add_message_to_thread(self, thread_id: str, prompt: str, image_data: Optional[str] = None):
        """
        Add a message to the thread, with optional image.
        
        Args:
            thread_id: The thread ID.
            prompt: The user's prompt text.
            image_data: Optional base64-encoded image data.
        """
        try:
            # Prepare the message content
            if image_data:
                # Add message with text and image
                content = [
                    {"type": "text", "text": prompt},
                ]
                
                # Add the image if available
                if image_data:
                    content.append({
                        "type": "image_url", 
                        "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}
                    })
            else:
                # Text-only message
                content = prompt
              # Add the message to the thread
            self.client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=content
            )
            logger.info(f"Added message to thread {thread_id}")
            return True
        except Exception as e:
            logger.error(f"Error adding message to thread: {e}")
            return False
            
    async def _run_assistant(self, thread_id: str, websocket=None) -> Optional[Dict[str, Any]]:
        """
        Run the assistant on the thread and retrieve the response.
        
        Args:
            thread_id: The thread ID.
            websocket: Optional websocket for status updates.
            
        Returns:
            dict: The parsed JSON response, or None if an error occurs.
        """
        try:
            # Run the assistant on the thread
            run = self.client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=self.assistant_id
            )
            
            # Poll for run completion
            status_map = {
                "queued": "Waiting in queue...",
                "in_progress": "Assistant is processing...",
                "requires_action": "Requires action",
                "cancelling": "Cancelling...",
                "cancelled": "Cancelled",
                "failed": "Failed",
                "completed": "Completed",
                "expired": "Expired"
            }
            
            while run.status in ["queued", "in_progress"]:
                if self.gpt_command_cancelled:
                    try:
                        self.client.beta.threads.runs.cancel(
                            thread_id=thread_id,
                            run_id=run.id
                        )
                        logger.info(f"Cancelled run {run.id}")
                    except Exception as cancel_e:
                        logger.error(f"Error cancelling run: {cancel_e}")
                    return None
                
                if websocket:
                    await self._send_gpt_status_update(
                        websocket, 
                        "progress", 
                        status_map.get(run.status, run.status)
                    )
                
                await asyncio.sleep(1)
                run = self.client.beta.threads.runs.get(
                    thread_id=thread_id,
                    run_id=run.id
                )
            
            if run.status != "completed":
                logger.error(f"Run failed with status: {run.status}")
                if websocket:
                    await self._send_gpt_status_update(
                        websocket, 
                        "error", 
                        f"Assistant run failed: {status_map.get(run.status, run.status)}"
                    )
                return None
            
            # Retrieve the latest message from the assistant
            messages = self.client.beta.threads.messages.list(
                thread_id=thread_id
            )
            
            # Find the most recent assistant message
            for message in messages.data:
                if message.role == "assistant":
                    # Parse the JSON content
                    try:
                        content_text = message.content[0].text.value
                        # Extract JSON from markdown code blocks if present
                        if "```json" in content_text and "```" in content_text:
                            # Extract JSON from markdown code block
                            import re
                            json_match = re.search(r'```json\n(.*?)\n```', content_text, re.DOTALL)
                            if json_match:
                                content_text = json_match.group(1)
                        
                        return json.loads(content_text)
                    except (json.JSONDecodeError, AttributeError, IndexError) as e:
                        logger.error(f"Error parsing assistant response: {e}")
                        logger.error(f"Raw message content: {message.content}")
                        if websocket:
                            await self._send_gpt_status_update(
                                websocket, 
                                "error", 
                                "Failed to parse assistant response"
                            )
                        return None
            
            logger.error("No assistant message found in thread")
            return None
            
        except Exception as e:
            logger.error(f"Error running assistant: {e}")
            return None

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
            # Create the base update object
            update = {
                "type": "gpt_status",
                "status": status,
                "message": message,
                "timestamp": time.time()
            }
            
            # Include additional data if provided
            if additional_data:
                update["data"] = additional_data
                
            await websocket.send_json(update)
        except Exception as e:
            logger.error(f"Error sending GPT status update: {str(e)}")    
    
    async def cancel_gpt_command(self, websocket=None):
        """
        Cancel the currently running GPT command and stop any running scripts or motor sequences.
        
        Args:
            websocket: Optional websocket to send status updates through.
        
        Returns:
            bool: True if a command was cancelled, False if no command was running.
        """
        if self.is_processing:
            logger.info("Cancelling GPT command")
            self.gpt_command_cancelled = True

            if websocket:
                await self._send_gpt_status_update(websocket, "cancelling", "Cancelling current command...")

            # Stop all active scripts
            for script_name in list(self.active_processes.keys()):
                self._stop_script(script_name)
                logger.info(f"Script {script_name} stopped due to cancellation")
            
            # Stop all motors immediately
            try:
                self.px.set_motor_speed(1, 0)  # rear_left
                self.px.set_motor_speed(2, 0)  # rear_right
                self.px.set_dir_servo_angle(0)  # front steering
                logger.info("All motors stopped due to cancellation")
            except Exception as e:
                logger.error(f"Error stopping motors during cancellation: {e}")
            
            # Restore the robot state to MANUAL_CONTROL explicitly
            old_state = self.sensor_manager.robot_state
            self.sensor_manager.robot_state = self.robot_state_enum.MANUAL_CONTROL
            logger.info(f"Robot state forcibly restored from {old_state} to {self.sensor_manager.robot_state}")
            
            # Reset the processing flag explicitly
            self.is_processing = False
            
            if websocket:
                await self._send_gpt_status_update(websocket, "cancelled", "Command cancelled successfully")
            
            return True
        
        if websocket:
            await self._send_gpt_status_update(websocket, "info", "No active command to cancel")
        
        return False
       
    async def _get_camera_image(self) -> Optional[str]:
        try:
            import requests
            response = requests.get("http://127.0.0.1:9000/mjpg.jpg", timeout=2)
            if response.status_code == 200:
                image_bytes = response.content
                image = Image.open(io.BytesIO(image_bytes))
                buffered = io.BytesIO()
                image.save(buffered, format="JPEG")
                encoded_image = base64.b64encode(buffered.getvalue()).decode("utf-8")
                return encoded_image
            else:
                logger.error(f"Failed to get camera image, status code: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error getting camera image: {e}")
            return None    
    async def _process_actions(self, response: Dict[str, Any], websocket=None) -> bool:
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
            response["language"] = language
        
        # For python_script action type, ensure TTS completes before script execution
        if action_type == "python_script":
            # First speak the text if available
            if text_output:
                # For python_script we need to wait until TTS is actually finished
                await self.tts_manager.say(text_output, priority=1, blocking=True, lang=language)
                # Double-check speaking is really done
                while self.tts_manager.is_speaking():
                    await asyncio.sleep(0.1)
              # Now run the script after TTS is completely done
            script_code = response.get("python_script", "")
            if script_code:
                return await run_script_in_isolated_environment(
                    script_code,
                    self.px,
                    self._get_camera_image,
                    self.tts_manager,
                    self.sound_manager,
                    self,
                    websocket,
                    run_in_background=False
                )
            else:
                await self.tts_manager.say("No Python script provided.", priority=1)
                return False
        else:
            # For other action types, speak the text but don't necessarily need to fully block
            if text_output:
                await self.tts_manager.say(text_output, priority=1, blocking=False, lang=language)
        
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
                        await self._execute_predefined_function(function_name, parameters)
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
    async def _stop_script(self, script_name: str) -> bool:
        """
        Stop a running script by setting the cancellation flag and waiting for it to terminate.
        Works with our new script execution environment.
        
        Args:
            script_name: The name of the script to stop
            
        Returns:
            bool: Success status
        """
        if script_name in self.active_processes:
            process_info = self.active_processes[script_name]
            try:
                # Set the cancellation flag first - this works with our new script runner
                self.gpt_command_cancelled = True
                
                # For thread-based execution (with 'future' and 'done_event')
                if isinstance(process_info, dict) and 'future' in process_info and 'done_event' in process_info:
                    logger.info(f"Waiting for script {script_name} to acknowledge cancellation...")
                    
                    # Give the thread a chance to notice the cancellation and clean up
                    # Don't wait indefinitely to avoid freezing the main thread
                    if not process_info['done_event'].wait(timeout=2.0):
                        logger.warning(f"Script {script_name} did not respond to cancellation signal within timeout")
                        
                        # Try to cancel the future if possible
                        if hasattr(process_info['future'], 'cancel'):
                            try:
                                process_info['future'].cancel()
                                logger.info(f"Forcibly cancelled future for {script_name}")
                            except Exception as future_err:
                                logger.error(f"Error cancelling future: {future_err}")
                    
                    logger.info(f"Cancelled script: {script_name}")
                    
                # For asyncio Tasks
                elif hasattr(process_info, 'cancel'):
                    # It's an asyncio Task
                    process_info.cancel()
                    logger.info(f"Cancelled async task: {script_name}")
                    
                # For subprocesses (legacy support)
                elif hasattr(process_info, 'terminate'):
                    # It's a subprocess.Popen
                    process_info.terminate()
                    process_info.wait(timeout=3)
                    if process_info.poll() is None:
                        process_info.kill()
                    logger.info(f"Terminated subprocess: {script_name}")
                    
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
                
                # Remove from active processes
                del self.active_processes[script_name]
                logger.info(f"Stopped script: {script_name}")
                return True
                
            except Exception as e:
                logger.error(f"Error stopping script {script_name}: {e}")
                # Ensure it's removed from active processes even if there was an error
                if script_name in self.active_processes:
                    del self.active_processes[script_name]
                return False
        else:
            logger.warning(f"No script named {script_name} is running")
            return False
    
    async def cleanup(self):
        for script_name in list(self.active_processes.keys()):
            self._stop_script(script_name)
        for file in self.temp_dir.glob("*.py"):
            try:
                file.unlink()
            except Exception as e:
                logger.error(f"Error removing temp file {file}: {e}")