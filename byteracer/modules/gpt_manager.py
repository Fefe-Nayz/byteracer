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
    async def process_gpt_command(self, prompt: str, use_camera: bool = False, websocket = None, new_conversation=False) -> bool:
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

            old_state = self.sensor_manager.robot_state
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
        "enum": ["en-us", "en-uk", "fr", "de", "es", "it"],
        "description": "The language for text-to-speech output. Default is English (US)."
      }
    },
    "required": [
      "action_type",
      "python_script",
      "predefined_functions",
      "motor_sequence",
      "text"
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
    - A helper function `get_camera_frame()` is available (returns a `cv2` image).
    - A `try/except/finally` block is added around your code to handle interruptions.
    - In `finally`, all motors are safely stopped.
- Your code will be inserted with indentation inside the `try:` block.

Please generate code that:
- Avoids re-instantiating `px`,
- Uses `await` and `asyncio.sleep()` if delays are needed (not `time.sleep()`),
- Uses `get_camera_frame()` for accessing the camera image.

If you want to manipulate motors or camera, call methods on `px` such as:
- `px.set_motor_speed("rear_left", speed)`
- `px.set_dir_servo_angle(angle)`
- `px.set_cam_pan_angle(angle)`

2. **Call predefined functions** (action_type: "predefined_function").  
   Available functions include:
      - move(motor_id: string, speed: number): Moves the specified motor at a given speed (0 to 100%).
      - turn(degrees: number): Rotates the robot by a specified number of degrees.
      - capture_image(): Captures a frame from the camera.
      - stop(): Immediately stops all motors.
      - adjust_camera(pan: number, tilt: number): Sets the camera’s pan and tilt angles.
      - … (include your full list of available functions with their parameters)
3. **Produce a motor sequence** (action_type: "motor_sequence") that groups a timeline of commands per motor.
   - For DC motors ("rear_left", "rear_right"): the only allowed command is **"set_speed"**.
   - For servo motors ("front", "cam_pan", "cam_tilt"): the only allowed command is **"set_angle"**.
   Each action includes:
      - timestamp (seconds from start),
      - command (either "set_speed" or "set_angle"),
      - value (numeric value for speed or angle).
4. **Provide textual feedback** (action_type: "none") for TTS and display.

Structured Output Format:
Return a JSON object with exactly these keys:
{
  "action_type": "string (one of: 'python_script', 'predefined_function', 'motor_sequence', 'none')",
  "python_script": "string (non-empty only if action_type is 'python_script')",
  "predefined_functions": [
      { "function_name": "string", "parameters": { ... } }
  ],
  "motor_sequence": [
      {
         "motor_id": "string (one of: 'rear_left', 'rear_right', 'front', 'cam_pan', 'cam_tilt')",
         "actions": [
             { "timestamp": number, "command": "string ('set_speed' or 'set_angle')", "value": number }
         ]
      }
  ],
  "text": "string (for TTS output and on-screen feedback)"
}

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
            self.sensor_manager.robot_state = self.robot_state_enum.CONTROLLED_BY_CLIENT
            logger.info(f"Robot state restored from {old_state} to {self.robot_state_enum.CONTROLLED_BY_CLIENT}")
                    
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
    
    def cancel_gpt_command(self):
        """
        Cancel the currently running GPT command.
        
        Returns:
            bool: True if a command was cancelled, False if no command was running.
        """
        if self.is_processing:
            logger.info("Cancelling GPT command")
            self.gpt_command_cancelled = True
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
        required_keys = ["action_type", "python_script", "predefined_functions", "motor_sequence", "text"]
        if not all(key in response for key in required_keys):
            await self.tts_manager.say("Received incomplete command instructions.", priority=1)
            return False
          # Always output TTS feedback.
        text_output = response.get("text", "")
        language = response.get("language", None)  # Get the language if specified
        
        if text_output:
            await self.tts_manager.say(text_output, priority=1, lang=language)
        
        action_type = response.get("action_type")
        if action_type == "python_script":
            script_code = response.get("python_script", "")
            if script_code:
                return await self._run_custom_script(f"script_{int(time.time())}", script_code, run_in_background=False)
            else:
                await self.tts_manager.say("No Python script provided.", priority=1)
                return False
        
        elif action_type == "predefined_function":
            functions = response.get("predefined_functions", [])
            if functions:
                for func_call in functions:
                    function_name = func_call.get("function_name", "")
                    parameters = func_call.get("parameters", {})
                    # Dispatch based on your complete set of predefined commands.
                    if function_name == "move":
                        speed = parameters.get("speed", 0)
                        motor_id = parameters.get("motor_id", "")
                        if motor_id:
                            self.px.set_motor_speed(motor_id, speed)
                    elif function_name == "turn":
                        degrees = parameters.get("degrees", 0)
                        self.px.turn(degrees)
                    # Add additional predefined commands here...
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
                self.px.set_motor_speed(2, -value)
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
        try:
            script_path = self.temp_dir / f"{script_name}.py"
            script_header = """
import os
import sys
import time
import asyncio
import logging
from picarx import Picarx
import cv2
import numpy as np
import requests
from io import BytesIO

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
px = Picarx()

def get_camera_frame():
    try:
        response = requests.get("http://127.0.0.1:9000/mjpg.jpg", timeout=1)
        if response.status_code == 200:
            image_bytes = response.content
            nparr = np.frombuffer(image_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            return frame
        else:
            logger.error(f"Failed to get camera image, status code: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Error getting camera image: {e}")
        return None

try:
"""
            indented_code = "\n".join(f"    {line}" for line in script_code.split("\n"))
            script_footer = """
except KeyboardInterrupt:
    logger.info("Script interrupted by user")
except Exception as e:
    logger.error(f"Script error: {e}")
finally:
    px.set_motor_speed("rear_left", 0)
    px.set_motor_speed("rear_right", 0)
    px.set_dir_servo_angle(0)
    logger.info("Script ended, motors stopped")
"""
            full_script = script_header + indented_code + script_footer
            with open(script_path, "w") as f:
                f.write(full_script)
            logger.info(f"Created script at {script_path}")
            if run_in_background:
                process = subprocess.Popen(["python3", str(script_path)],
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE)
                self.active_processes[script_name] = process
                logger.info(f"Running script {script_name} in background, PID: {process.pid}")
                await self.tts_manager.say(f"Running {script_name} in the background.", priority=1)
            else:
                await self.tts_manager.say(f"Running {script_name}.", priority=1)
                process = await asyncio.create_subprocess_exec("python3", str(script_path),
                                                                stdout=asyncio.subprocess.PIPE,
                                                                stderr=asyncio.subprocess.PIPE)
                stdout, stderr = await process.communicate()
                if process.returncode != 0:
                    logger.error(f"Script error: {stderr.decode()}")
                    await self.tts_manager.say("The script encountered an error.", priority=1)
                    return False
                logger.info(f"Script completed: {stdout.decode()}")
                await self.tts_manager.say("Script completed.", priority=1)
            return True
        except Exception as e:
            logger.error(f"Error running custom script: {e}")
            return False
    
    def _stop_script(self, script_name: str) -> bool:
        if script_name in self.active_processes:
            process = self.active_processes[script_name]
            try:
                process.terminate()
                process.wait(timeout=3)
                if process.poll() is None:
                    process.kill()
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