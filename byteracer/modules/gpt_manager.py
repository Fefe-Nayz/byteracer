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

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
                await self._send_gpt_status_update(websocket, "info", "Created new conversation thread.")
            
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

            old_state = robot_state if robot_state is not None else self.robot_state_enum.WAITING_FOR_INPUT
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
"parameters": {
              "type": "object",
              "description": "A JSON object containing the parameters for the function.",
              "additionalProperties": True
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
                            "strict": False
                        }
                    },
                    "instructions": """
                    You are ByteRacer, a small remote-controlled robot car with AI capabilities.
Hardware and Capabilities:
- **Motors:** The robot has five controllable devices with predictable IDs:
    • "rear_left": A DC motor (set speed command, valid range -100 to 100).
    • "rear_right": A DC motor (set speed command, valid range -100 to 100).
    • "front": A servo motor for steering (set angle command, valid range -30 to 30 degrees).
    • "cam_pan": A servo motor for camera panning (set angle command, valid range -90 to 90 degrees).
    • "cam_tilt": A servo motor for camera tilting (set angle command, valid range -35 to 65 degrees).
- **Camera Feed:** Available in real time for visual analysis.
- **Additional Sensors:** Ultrasonic sensor (front) and line following sensors (bottom).

Tasks:
1. **Generate a Python script** (action_type: "python_script") if complex behaviors are needed.
When generating a Python script (`action_type: "python_script"`), keep in mind:

- The script will be executed on a real robot (ByteRacer), using a `Picarx` instance called `px`.
- The generated script is wrapped inside a predefined header/footer:
    - The `px` object is already instantiated.
    - A helper function `get_camera_image()` is available (returns base64-encoded image data).
    - You can also say custom things in your python code with `await tts.say("Your message", priority=1, lang="The language code of the message")`.
    - You can play sounds using `sound.play_sound("sound_name")`. (see available sounds below)
    - A `try/except/finally` block is added around your code to handle interruptions.
    - In `finally`, all motors are safely stopped.
- Your code will be inserted with indentation inside the `try:` block.

If you want to manipulate motors or camera, call methods on `px` such as:
- `px.set_motor_speed(1, speed)` # for rear_left motor
- `px.set_motor_speed(2, -speed)` # for rear_right motor (the speed should be reversed because the motor is placed in reverse, THIS IS ALSO TTHE CASE IN THE MOTOR SEQUENCE)
- `px.set_dir_servo_angle(angle)`
- `px.set_cam_pan_angle(angle)`

You can also read the sensor values using `px` methods like:
- `px.get_distance()` for ultrasonic sensor (returns distance in cm).
- `px.get_line_sensor_value()` for line following sensors (returns a list of values).

2. **Call predefined functions** (action_type: "predefined_function").  
   Available functions include:
      - move(motor_id: string, speed: number): Moves the specified motor at a given speed (-100 to 100%).
      - move_forward(speed: number): Moves the robot forward at specified speed (0 to 100%).
      - move_backward(speed: number): Moves the robot backward at specified speed (0 to 100%).
      - stop(): Immediately stops all motors.
      - turn(angle: number): Sets the steering servo angle (-30 to 30 degrees).
      - set_camera_angle(pan: number, tilt: number): Sets camera pan (-90 to 90) and tilt (-35 to 65) angles.
      - get_distance(): Returns the ultrasonic sensor distance measurement.
      - play_sound(sound_name: string): Plays a sound effect by name. 
          - The available sounds are: "alarm", "aurores", "bruh", "cailloux", "fart", "get-out", "india", "klaxon", "klaxon-2", "laugh", "lingango", "nope", "ph", "pipe", "rat-dance", "scream", "tralalelo-tralala", "tuile", "vine-boom", "wow" and "wtf'
      - say(text: string, language: string): Uses text-to-speech to make the robot talk.
      - get_sensor_data(): Gets all sensor readings (ultrasonic, line, battery, etc).
      
      Sound settings:
      - set_sound_enabled(enabled: boolean): Enables or disables all sounds.
      - set_sound_volume(volume: number): Sets master sound volume (0-100).
      - set_sound_effect_volume(volume: number): Sets sound effects volume (0-100).
      - set_tts_enabled(enabled: boolean): Enables or disables text-to-speech.
      - set_tts_volume(volume: number): Sets TTS master volume (0-100).
      - set_tts_language(language: string): Sets TTS language (en-US, en-GB, de-DE, es-ES, fr-FR, it-IT).
      - set_category_volume(category: string, volume: number): Sets volume for specific category (driving, alert, custom, voice).
      - set_tts_audio_gain(gain: number): Sets TTS audio gain (1.0-15.0).
      - set_user_tts_volume(volume: number): Sets volume for user TTS messages (0-100).
      - set_system_tts_volume(volume: number): Sets volume for system TTS messages (0-100).
      - set_emergency_tts_volume(volume: number): Sets volume for emergency TTS messages (0-100).
      
      Safety settings:
      - set_collision_avoidance(enabled: boolean): Enables or disables collision avoidance.
      - set_collision_threshold(threshold: number): Sets distance threshold for collision detection (10-100cm).
      - set_edge_detection(enabled: boolean): Enables or disables edge detection.
      - set_edge_threshold(threshold: number): Sets threshold for edge detection (0.1-0.9).
      - set_auto_stop(enabled: boolean): Enables or disables automatic stopping for safety.
      - set_client_timeout(timeout: number): Sets client timeout in seconds (1-30).
      
      Drive settings:
      - set_max_speed(speed: number): Sets maximum speed percentage (0-100).
      - set_max_turn_angle(angle: number): Sets maximum turn angle percentage (0-100).
      - set_acceleration_factor(factor: number): Sets acceleration factor (0.1-1.0).
      - set_enhanced_turning(enabled: boolean): Enables or disables enhanced turning.
      - set_turn_in_place(enabled: boolean): Enables or disables turning in place.
      
      Camera settings:
      - set_camera_flip(vflip: boolean, hflip: boolean): Sets vertical and horizontal camera flipping.
      - set_camera_display(local_display: boolean, web_display: boolean): Sets camera display options.
      - set_camera_size(width: number, height: number): Sets camera resolution.
      
      System commands:
      - restart_robot(): Restarts the entire robot system.
      - shutdown_robot(): Shuts down the robot system.
      - restart_all_services(): Restarts all robot services.
      - restart_websocket(): Restarts the websocket service.
      - restart_web_server(): Restarts the web server.
      - restart_python_service(): Restarts the Python service.
      - restart_camera_feed(): Restarts the camera feed.
      - check_for_updates(): Checks for and applies software updates.
      - emergency_stop(): Activates emergency stop.
      - clear_emergency(): Clears emergency stop status.
      
      Predefined animations:
      - wave_hands(): Makes the robot wave its front wheels.
      - nod(): Makes the robot nod its camera.
      - shake_head(): Makes the robot shake its camera from side to side.
      - act_cute(): Makes the robot perform a cute animation.
      - think(): Makes the robot appear to be thinking.
      - keep_think(): Makes the robot keep thinking.
      - celebrate(): Makes the robot perform a celebratory animation.
      - resist(): Makes the robot perform a resistance animation.
      - twist_body(): Makes the robot twist its body.
      - rub_hands(): Makes the robot rub its front wheels.
      - depressed(): Makes the robot appear depressed.
3. **Produce a motor sequence** (action_type: "motor_sequence") that groups a timeline of commands per motor.
   - For DC motors ("rear_left", "rear_right"): the only allowed command is **"set_speed"**.
   - For servo motors ("front", "cam_pan", "cam_tilt"): the only allowed command is **"set_angle"**.
   Each action includes:
      - timestamp (seconds from start),
      - command (either "set_speed" or "set_angle"),
      - value (numeric value for speed or angle).
4. **Provide textual feedback** (action_type: "none") for TTS and display.
5. **Specify the language** for TTS output (e.g., "en-US", "de-DE").

Structured Output Format:
Return a JSON object with exactly these keys:
```json
{
  "action_type": "string (one of: 'python_script', 'predefined_function', 'motor_sequence', 'none')",
  "python_script": "string (non-empty only if action_type is 'python_script')",
  "predefined_functions": [
      { "function_name": "string", "parameters": { ... } }
  ],
  "motor_sequence": [
      {
         "motor_id": "string ('rear_left', 'rear_right', 'front', 'cam_pan', 'cam_tilt')",
         "actions": [
             { "timestamp": number, "command": "string ('set_speed' or 'set_angle')", "value": number }
         ]
      }
  ],
  "text": "string (for TTS output and on-screen feedback)",
  "language": "string (one of: 'en-US', 'en-GB', 'de-DE', 'es-ES', 'fr-FR', 'it-IT')"
}
```
ALL TTHE FILED MUST ALWAYS BE INCLUDED. FOLLOW THE RESPONSE FORMAT STRICTLY.
When a field is not applicable, leave it empty.
Tone: Cheerful, optimistic, humorous, and playful.
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
                                            return False
                                                
                                        # Send update about executing actions
                                        if websocket:
                                            await self._send_gpt_status_update(websocket, "progress", "Executing actions...")
                                        
                                        success = await self._process_actions(parsed_response)
                                        
                                        if websocket:
                                            if success:
                                                await self._send_gpt_status_update(websocket, "completed", "Command completed successfully")
                                            else:
                                                await self._send_gpt_status_update(websocket, "error", "Command execution failed")
                                        
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
            if old_state != self.robot_state_enum.WAITING_FOR_INPUT:
                # Only restore to previous state if it wasn't the waiting state
                self.sensor_manager.robot_state = old_state
            else:
                # If previous state was waiting, set to client controlled
                self.sensor_manager.robot_state = self.robot_state_enum.CONTROLLED_BY_CLIENT
            
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
            openai.beta.threads.messages.create(
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
            run = openai.beta.threads.runs.create(
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
                        openai.beta.threads.runs.cancel(
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
                run = openai.beta.threads.runs.retrieve(
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
            messages = openai.beta.threads.messages.list(
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

    async def _send_gpt_status_update(self, websocket, status_type, message):
        """
        Send status updates about GPT command processing to the client.
        
        Args:
            websocket: WebSocket connection to the client.
            status_type: Type of status update (starting, progress, completed, error, warning, cancelled).
            message: Status message details.
        """
        try:
            status_update = {
                "name": "gpt_status_update",
                "data": {
                    "status": status_type,
                    "message": message,
                    "timestamp": int(time.time() * 1000)
                },
                "createdAt": int(time.time() * 1000)
            }
            await websocket.send(json.dumps(status_update))
            logger.debug(f"Sent GPT status update: {status_type} - {message}")
        except Exception as e:
            logger.error(f"Error sending GPT status update: {e}")
    async def cancel_gpt_command(self):
        """
        Cancel the currently running GPT command and stop any running scripts or motor sequences.
        
        Returns:
            bool: True if a command was cancelled, False if no command was running.
        """
        if self.is_processing:
            logger.info("Cancelling GPT command")
            self.gpt_command_cancelled = True

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
            
            return True
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
    async def _process_actions(self, response: Dict[str, Any]) -> bool:
        required_keys = ["action_type", "python_script", "predefined_functions", "motor_sequence", "text", "language"]
        if not all(key in response for key in required_keys):
            await self.tts_manager.say("Received incomplete command instructions.", priority=1)
            return False
        
        # Get text output and language
        text_output = response.get("text", "")
        language = response.get("language", None)  # Get the language if specified
        action_type = response.get("action_type")
        
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
                return await self._run_custom_script(f"script_{int(time.time())}", script_code, run_in_background=False)
            else:
                await self.tts_manager.say("No Python script provided.", priority=1)
                return False
        else:
            # For other action types, speak the text but don't need to fully block
            if text_output:
                await self.tts_manager.say(text_output, priority=1, blocking=False, lang=language)
        
        if action_type == "predefined_function":
            functions = response.get("predefined_functions", [])
            if functions:
                for func_call in functions:
                    function_name = func_call.get("function_name", "")
                    parameters = func_call.get("parameters", {})                    # Dispatch based on your complete set of predefined commands.
                    if function_name == "move":
                        speed = parameters.get("speed", 0)
                        motor_id = parameters.get("motor_id", "")
                        if motor_id == "rear_left":
                            self.px.set_motor_speed(1, speed)
                        elif motor_id == "rear_right":
                            self.px.set_motor_speed(2, speed)
                        else:
                            logger.warning(f"Unknown motor_id {motor_id}")
                    elif function_name == "move_forward":
                        speed = parameters.get("speed", 50)
                        self.px.forward(speed)
                    elif function_name == "move_backward":
                        speed = parameters.get("speed", 50)
                        self.px.backward(speed)
                    elif function_name == "stop":
                        self.px.stop()
                    elif function_name == "turn":
                        angle = parameters.get("angle", 0)
                        self.px.set_dir_servo_angle(angle)
                    elif function_name == "set_camera_angle":
                        pan = parameters.get("pan", None)
                        tilt = parameters.get("tilt", None)
                        if pan is not None:
                            self.px.set_cam_pan_angle(pan)
                        if tilt is not None:
                            self.px.set_cam_tilt_angle(tilt)
                    elif function_name == "get_distance":
                        # Return the distance measurement from ultrasonic sensor
                        distance = self.px.get_distance()
                        self.tts_manager.say(f"Distance: {distance} cm", priority=1)
                        logger.info(f"Ultrasonic distance: {distance} cm")
                    elif function_name == "play_sound":
                        sound_name = parameters.get("sound_name", "")
                        if sound_name and self.sound_manager:
                            self.sound_manager.play_sound(sound_name)
                        else:
                            logger.warning(f"Sound '{sound_name}' not found or sound manager not available")
                    elif function_name == "say":
                        text = parameters.get("text", "")
                        language = parameters.get("language", "en-US")
                        if text and self.tts_manager:
                            asyncio.create_task(self.tts_manager.say(text, lang=language))
                        else:
                            logger.warning("Text not provided or TTS manager not available")
                    # Predefined animations from preset_actions.py
                    elif function_name == "wave_hands":
                        from modules.gpt.preset_actions import wave_hands
                        wave_hands(self.px)
                    elif function_name == "nod":
                        from modules.gpt.preset_actions import nod
                        nod(self.px)
                    elif function_name == "shake_head":
                        from modules.gpt.preset_actions import shake_head
                        shake_head(self.px)
                    elif function_name == "act_cute":
                        from modules.gpt.preset_actions import act_cute
                        act_cute(self.px)
                    elif function_name == "think":
                        from modules.gpt.preset_actions import think
                        think(self.px)
                    elif function_name == "keep_think": 
                        from modules.gpt.preset_actions import keep_think
                        keep_think(self.px)
                    elif function_name == "celebrate":
                        from modules.gpt.preset_actions import celebrate
                        celebrate(self.px)
                    elif function_name == "resist":
                        from modules.gpt.preset_actions import resist
                        resist(self.px)
                    elif function_name == "twist_body":
                        from modules.gpt.preset_actions import twist_body
                        twist_body(self.px)
                    elif function_name == "rub_hands":
                        from modules.gpt.preset_actions import rub_hands
                        rub_hands(self.px)
                    elif function_name == "depressed":
                        from modules.gpt.preset_actions import depressed
                        depressed(self.px)
                    # Add sensor state functions                    elif function_name == "get_sensor_data":
                        sensor_data = self.sensor_manager.get_sensor_data()
                        logger.info(f"Sensor data: {sensor_data}")
                    
                    # Sound settings
                    elif function_name == "set_sound_enabled":
                        enabled = parameters.get("enabled", True)
                        self.config_manager.set("sound.enabled", enabled)
                        self.sound_manager.set_enabled(enabled)
                        logger.info(f"Sound enabled set to {enabled}")
                        
                    elif function_name == "set_sound_volume":
                        volume = parameters.get("volume", 50)
                        if 0 <= volume <= 100:
                            self.config_manager.set("sound.volume", volume)
                            self.sound_manager.set_volume(volume)
                            logger.info(f"Sound volume set to {volume}")
                        else:
                            logger.warning(f"Invalid sound volume: {volume}")
                    
                    elif function_name == "set_sound_effect_volume":
                        volume = parameters.get("volume", 50)
                        if 0 <= volume <= 100:
                            self.config_manager.set("sound.sound_volume", volume)
                            self.sound_manager.set_sound_volume(volume)
                            logger.info(f"Sound effect volume set to {volume}")
                        else:
                            logger.warning(f"Invalid sound effect volume: {volume}")
                    
                    # TTS settings
                    elif function_name == "set_tts_enabled":
                        enabled = parameters.get("enabled", True)
                        self.config_manager.set("sound.tts_enabled", enabled)
                        self.tts_manager.set_enabled(enabled)
                        logger.info(f"TTS enabled set to {enabled}")
                    
                    elif function_name == "set_tts_volume":
                        volume = parameters.get("volume", 50)
                        if 0 <= volume <= 100:
                            self.config_manager.set("sound.tts_volume", volume)
                            self.tts_manager.set_volume(volume)
                            logger.info(f"TTS volume set to {volume}")
                        else:
                            logger.warning(f"Invalid TTS volume: {volume}")
                    
                    elif function_name == "set_tts_language":
                        language = parameters.get("language", "en-US")
                        valid_languages = ["en-US", "en-GB", "de-DE", "es-ES", "fr-FR", "it-IT"]
                        if language in valid_languages:
                            self.config_manager.set("sound.tts_language", language)
                            self.tts_manager.set_language(language)
                            logger.info(f"TTS language set to {language}")
                        else:
                            logger.warning(f"Invalid TTS language: {language}")
                    
                    elif function_name == "set_category_volume":
                        category = parameters.get("category", "")
                        volume = parameters.get("volume", 50)
                        valid_categories = ["driving", "alert", "custom", "voice"]
                        if category in valid_categories and 0 <= volume <= 100:
                            self.config_manager.set(f"sound.{category}_volume", volume)
                            self.sound_manager.set_category_volume(category, volume)
                            logger.info(f"{category} volume set to {volume}")
                        else:
                            logger.warning(f"Invalid category or volume: {category}={volume}")
                    
                    elif function_name == "set_tts_audio_gain":
                        gain = parameters.get("gain", 1.0)
                        if 1 <= gain <= 15.0:
                            self.config_manager.set("sound.tts_audio_gain", gain)
                            self.tts_manager.set_tts_audio_gain(gain)
                            logger.info(f"TTS audio gain set to {gain}")
                        else:
                            logger.warning(f"Invalid TTS audio gain: {gain}")
                    
                    elif function_name == "set_user_tts_volume":
                        volume = parameters.get("volume", 50)
                        if 0 <= volume <= 100:
                            self.config_manager.set("sound.user_tts_volume", volume)
                            self.tts_manager.set_user_tts_volume(volume)
                            logger.info(f"User TTS volume set to {volume}")
                        else:
                            logger.warning(f"Invalid user TTS volume: {volume}")

                    elif function_name == "set_system_tts_volume":
                        volume = parameters.get("volume", 50)
                        if 0 <= volume <= 100:
                            self.config_manager.set("sound.system_tts_volume", volume)
                            self.tts_manager.set_system_tts_volume(volume)
                            logger.info(f"System TTS volume set to {volume}")
                        else:
                            logger.warning(f"Invalid system TTS volume: {volume}")
                    
                    elif function_name == "set_emergency_tts_volume":
                        volume = parameters.get("volume", 50)
                        if 0 <= volume <= 100:
                            self.config_manager.set("sound.emergency_tts_volume", volume)
                            self.tts_manager.set_emergency_tts_volume(volume)
                            logger.info(f"Emergency TTS volume set to {volume}")
                        else:
                            logger.warning(f"Invalid emergency TTS volume: {volume}")
                    
                    # Safety settings
                    elif function_name == "set_collision_avoidance":
                        enabled = parameters.get("enabled", True)
                        self.config_manager.set("safety.collision_avoidance", enabled)
                        self.sensor_manager.set_collision_avoidance(enabled)
                        logger.info(f"Collision avoidance set to {enabled}")
                    
                    elif function_name == "set_collision_threshold":
                        threshold = parameters.get("threshold", 20)
                        if 10 <= threshold <= 100:
                            self.config_manager.set("safety.collision_threshold", threshold)
                            self.sensor_manager.collision_threshold = threshold
                            logger.info(f"Collision threshold set to {threshold}")
                        else:
                            logger.warning(f"Invalid collision threshold: {threshold}")
                    
                    elif function_name == "set_edge_detection":
                        enabled = parameters.get("enabled", True)
                        self.config_manager.set("safety.edge_detection", enabled)
                        self.sensor_manager.set_edge_detection(enabled)
                        logger.info(f"Edge detection set to {enabled}")
                    
                    elif function_name == "set_edge_threshold":
                        threshold = parameters.get("threshold", 0.1)
                        if 0.1 <= threshold <= 0.9:
                            self.config_manager.set("safety.edge_threshold", threshold)
                            self.sensor_manager.set_edge_detection_threshold(threshold)
                            logger.info(f"Edge threshold set to {threshold}")
                        else:
                            logger.warning(f"Invalid edge threshold: {threshold}")
                    
                    elif function_name == "set_auto_stop":
                        enabled = parameters.get("enabled", True)
                        self.config_manager.set("safety.auto_stop", enabled)
                        self.sensor_manager.set_auto_stop(enabled)
                        logger.info(f"Auto stop set to {enabled}")

                    elif function_name == "set_client_timeout":
                        timeout = parameters.get("timeout", 10)
                        if 1 <= timeout <= 30:
                            self.config_manager.set("safety.client_timeout", timeout)
                            self.sensor_manager.client_timeout = timeout
                            logger.info(f"Client timeout set to {timeout} seconds")
                        else:
                            logger.warning(f"Invalid client timeout: {timeout}")
                    
                    # Drive settings
                    elif function_name == "set_max_speed":
                        speed = parameters.get("speed", 50)
                        if 0 <= speed <= 100:
                            self.config_manager.set("drive.max_speed", speed)
                            logger.info(f"Max speed set to {speed}")
                        else:
                            logger.warning(f"Invalid max speed: {speed}")
                    
                    elif function_name == "set_max_turn_angle":
                        angle = parameters.get("angle", 50)
                        if 0 <= angle <= 100:
                            self.config_manager.set("drive.max_turn_angle", angle)
                            logger.info(f"Max turn angle set to {angle}")
                        else:
                            logger.warning(f"Invalid max turn angle: {angle}")
                    
                    elif function_name == "set_acceleration_factor":
                        factor = parameters.get("factor", 0.5)
                        if 0.1 <= factor <= 1.0:
                            self.config_manager.set("drive.acceleration_factor", factor)
                            logger.info(f"Acceleration factor set to {factor}")
                        else:
                            logger.warning(f"Invalid acceleration factor: {factor}")
                    
                    elif function_name == "set_enhanced_turning":
                        enabled = parameters.get("enabled", True)
                        self.config_manager.set("drive.enhanced_turning", enabled)
                        logger.info(f"Enhanced turning set to {enabled}")
                    
                    elif function_name == "set_turn_in_place":
                        enabled = parameters.get("enabled", True)
                        self.config_manager.set("drive.turn_in_place", enabled)
                        logger.info(f"Turn in place set to {enabled}")
                    
                    # Camera settings
                    elif function_name == "set_camera_flip":
                        vflip = parameters.get("vflip", False)
                        hflip = parameters.get("hflip", False)
                        restart_needed = False
                        
                        self.config_manager.set("camera.vflip", vflip)
                        restart_needed |= self.camera_manager.update_settings(vflip=vflip)
                        
                        self.config_manager.set("camera.hflip", hflip)
                        restart_needed |= self.camera_manager.update_settings(hflip=hflip)
                        
                        if restart_needed:
                            asyncio.create_task(self.camera_manager.restart())
                        logger.info(f"Camera flip settings updated: vflip={vflip}, hflip={hflip}")
                    
                    elif function_name == "set_camera_display":
                        local = parameters.get("local_display", False)
                        web = parameters.get("web_display", True)
                        restart_needed = False
                        
                        self.config_manager.set("camera.local_display", local)
                        restart_needed |= self.camera_manager.update_settings(local=local)
                        
                        self.config_manager.set("camera.web_display", web)
                        restart_needed |= self.camera_manager.update_settings(web=web)
                        
                        if restart_needed:
                            asyncio.create_task(self.camera_manager.restart())
                        logger.info(f"Camera display settings updated: local={local}, web={web}")
                    
                    elif function_name == "set_camera_size":
                        width = parameters.get("width", 640)
                        height = parameters.get("height", 480)
                        camera_size = [width, height]
                        
                        self.config_manager.set("camera.camera_size", camera_size)
                        restart_needed = self.camera_manager.update_settings(camera_size=camera_size)
                        
                        if restart_needed:
                            asyncio.create_task(self.camera_manager.restart())
                        logger.info(f"Camera size updated to {width}x{height}")
                    
                    
                    # System commands
                    elif function_name == "restart_robot":
                        await self.tts_manager.say("Restarting system. Please wait.", priority=2, blocking=True)
                        logger.info("Restarting robot system")
                        # Schedule system reboot after response is sent
                        import threading
                        threading.Timer(2.0, lambda: subprocess.run("sudo reboot", shell=True)).start()
                    
                    elif function_name == "shutdown_robot":
                        await self.tts_manager.say("Shutting down system. Goodbye!", priority=2, blocking=True)
                        logger.info("Shutting down robot system")
                        import threading
                        threading.Timer(2.0, lambda: subprocess.run("sudo shutdown -h now", shell=True)).start()
                    
                    elif function_name == "restart_all_services":
                        await self.tts_manager.say("Restarting all services.", priority=1)
                        logger.info("Restarting all services")
                        import threading, os
                        project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
                        subprocess.Popen(
                            ["bash", f"{project_dir}/byteracer/scripts/restart_services.sh"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            start_new_session=True
                        )
                    
                    elif function_name == "restart_websocket":
                        await self.tts_manager.say("Restarting websocket service.", priority=1)
                        logger.info("Restarting websocket service")
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
                    
                    elif function_name == "restart_web_server":
                        await self.tts_manager.say("Restarting web server.", priority=1)
                        logger.info("Restarting web server")
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
                    
                    elif function_name == "restart_python_service":
                        await self.tts_manager.say("Restarting Python service.", priority=1)
                        logger.info("Restarting Python service")
                        import os
                        project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
                        subprocess.Popen(
                            ["bash", f"{project_dir}/byteracer/scripts/restart_python.sh"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            start_new_session=True
                        )
                    
                    elif function_name == "restart_camera_feed":
                        await self.tts_manager.say("Restarting camera feed.", priority=1)
                        logger.info("Restarting camera feed")
                        success = await self.camera_manager.restart()
                        if not success:
                            await self.tts_manager.say("Failed to restart camera feed.", priority=1)
                            logger.error("Failed to restart camera feed")
                    
                    elif function_name == "check_for_updates":
                        await self.tts_manager.say("Checking for updates.", priority=1)
                        logger.info("Checking for updates")
                        import os
                        project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
                        subprocess.Popen(
                            ["bash", f"{project_dir}/byteracer/scripts/update.sh"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            start_new_session=True
                        )
                    
                    elif function_name == "emergency_stop":
                        await self.tts_manager.say("Emergency stop activated.", priority=2)
                        logger.info("Emergency stop activated")
                        self.sensor_manager.manual_emergency_stop()
                    
                    elif function_name == "clear_emergency":
                        await self.tts_manager.say("Emergency stop cleared.", priority=1)
                        logger.info("Emergency stop cleared")
                        self.sensor_manager.clear_manual_stop()
                        
                    else:
                        logger.warning(f"Unknown predefined function {function_name}")
                return True
            else:
                await self.tts_manager.say("No predefined functions specified.", priority=1)
                return False
        
        elif action_type == "motor_sequence":
            motor_sequence = response.get("motor_sequence", [])
            if motor_sequence:
                motor_tasks = []
                for motor in motor_sequence:
                    motor_tasks.append(asyncio.create_task(self._run_motor_sequence(motor)))
                await asyncio.gather(*motor_tasks)
                return True
            else:
                await self.tts_manager.say("Motor sequence is empty.", priority=1)
                return False
        
        elif action_type == "none":
            return True
        
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
    async def _run_custom_script(self, script_name: str, script_code: str, run_in_background: bool) -> bool:
        """
        Runs the given user code in *this* process using `exec`, so the same `px` instance is reused.
        This avoids the 'GPIO busy' errors caused by creating a second Picarx() in a separate process.
        """
        logger = logging.getLogger(__name__)

        # Build an async function that encloses the user code inside our standard try/except/finally.
        # We indent the user code so it fits under `try:`.
        script_header = (
            "import asyncio\n\n"
            "async def user_script(px, get_camera_image, logger, tts, sound,  gpt_manager):\n"
            "    try:\n"
            "        # Check for cancellation before starting\n"
            "        if gpt_manager.gpt_command_cancelled:\n"
            "            logger.info(\"Script cancelled before execution\")\n"
            "            return\n\n"
            "        # Add regular cancellation checks\n"
            "        async def check_cancellation():\n"
            "            while not gpt_manager.gpt_command_cancelled:\n"
            "                await asyncio.sleep(0.2)\n"
            "            logger.info(\"Cancellation detected, stopping script\")\n"
            "            raise KeyboardInterrupt()\n"
            "        \n"
            "        # Start cancellation checker task\n"
            "        cancellation_task = asyncio.create_task(check_cancellation())\n"
            "        \n"
        )
        indented_user_code = "\n".join(f"        {line}" for line in script_code.split("\n"))
        script_footer = (
            "\n"
            "        # Clean up cancellation task\n"
            "        if not cancellation_task.done():\n"
            "            cancellation_task.cancel()\n"
            "    except KeyboardInterrupt:\n"
            "        logger.info(\"Script interrupted by user or cancellation\")\n"
            "    except Exception as e:\n"
            "        logger.error(f\"Script error: {e}\")\n"
            "    finally:\n"
            "        px.set_motor_speed(1, 0)\n"
            "        px.set_motor_speed(2, 0)\n"
            "        px.set_dir_servo_angle(0)\n"
            "        logger.info(\"Script ended, motors stopped\")\n"
        )        
        full_script = script_header + indented_user_code + script_footer

        # Prepare a local namespace where the script will be executed
        local_env = {}

        try:
            # "Compile" the script so that user_script(px, ...) is defined in local_env
            exec(full_script, local_env)

            # Grab the user_script function we just defined
            user_script = local_env["user_script"]

            # Create a task for tracking purposes
            if run_in_background:
                # Fire-and-forget in background: the user_script runs concurrently,
                # but we store the task reference so we can cancel it later
                task = asyncio.create_task(user_script(self.px, self._get_camera_image, logger, self.tts_manager, self.sound_manager, self))
                self.active_processes[script_name] = task
                logger.info(f"Running script '{script_name}' in the background.")
            else:
                # Run in the foreground: we await the user's async function here
                logger.info(f"Running script '{script_name}' in the foreground.")
                await user_script(self.px, self._get_camera_image, logger, self.tts_manager, self.sound_manager, self)

            return True

        except Exception as e:
            logger.error(f"Error running custom script: {e}")
            await self.tts_manager.say("The script encountered an error.", priority=1)
            return False

    async def _stop_script(self, script_name: str) -> bool:
        """
        Stop a running script, whether it's a subprocess or an asyncio task.
        
        Args:
            script_name: The name of the script to stop
            
        Returns:
            bool: Success status
        """
        if script_name in self.active_processes:
            process_or_task = self.active_processes[script_name]
            try:
                # Check if it's an asyncio Task
                if hasattr(process_or_task, 'cancel'):
                    # It's an asyncio Task
                    process_or_task.cancel()
                    logger.info(f"Cancelled async task: {script_name}")
                else:
                    # It's a subprocess.Popen
                    process_or_task.terminate()
                    process_or_task.wait(timeout=3)
                    if process_or_task.poll() is None:
                        process_or_task.kill()
                    logger.info(f"Terminated subprocess: {script_name}")
                
                # Remove from active processes
                del self.active_processes[script_name]
                logger.info(f"Stopped script: {script_name}")
                return True
            except Exception as e:
                logger.error(f"Error stopping script {script_name}: {e}")
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