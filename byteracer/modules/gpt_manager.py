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
import requests
from pathlib import Path
from PIL import Image
from typing import Dict, List, Any, Optional, Union

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GPTManager:
    """
    Manages interactions with GPT models to control the robot based on natural language commands.
    Uses structured outputs to perform various actions like:
    - Motor control for dancing or movement
    - Camera feed analysis
    - Sound playback
    - Text-to-speech
    - Running custom scripts
    """
    
    def __init__(self, px, camera_manager, tts_manager, sound_manager):
        """
        Initialize the GPT manager with references to other system components.
        
        Args:
            px: Picarx instance for hardware control
            camera_manager: Camera manager for accessing camera feed
            tts_manager: TTS manager for text-to-speech output
            sound_manager: Sound manager for audio playback
        """
        self.px = px
        self.camera_manager = camera_manager
        self.tts_manager = tts_manager
        self.sound_manager = sound_manager
        
        # OpenAI API settings
        self.api_key = os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            logger.warning("OPENAI_API_KEY not found in environment variables")
        
        # Configure API parameters
        self.model = "gpt-4-vision-preview"  # Use vision model for image processing
        self.max_tokens = 2000
        self.temperature = 0.7
        
        # Temporary directory for custom scripts
        self.temp_dir = Path(tempfile.gettempdir()) / "byteracer_scripts"
        os.makedirs(self.temp_dir, exist_ok=True)
        logger.info(f"Using temporary directory for scripts: {self.temp_dir}")
        
        # Keep track of running processes
        self.active_processes = {}
    
    async def process_gpt_command(self, prompt: str, use_camera: bool = False) -> bool:
        """
        Process a GPT command with the option to include camera feed.
        
        Args:
            prompt: The natural language command from the user
            use_camera: Whether to include the camera feed in the prompt
            
        Returns:
            bool: Success status
        """
        try:
            # Prepare system prompt with context about the robot
            system_prompt = self._get_system_prompt()
            
            # Get camera image if requested
            image_data = None
            if use_camera and self.camera_manager.is_active():
                image_data = await self._get_camera_image()
                if not image_data:
                    await self.tts_manager.say("Unable to access camera feed. Processing without image.", priority=1)
            
            # Create messages for GPT
            messages = self._create_messages(system_prompt, prompt, image_data)
            
            # Call OpenAI API with structured output format
            response = await self._call_openai_api(messages)
            
            if not response:
                await self.tts_manager.say("I couldn't process your request. Please try again.", priority=1)
                return False
            
            # Process the actions from the response
            success = await self._process_actions(response)
            return success
            
        except Exception as e:
            logger.error(f"Error processing GPT command: {e}")
            logger.error(traceback.format_exc())
            await self.tts_manager.say(f"I encountered an error while processing your request. {str(e)}", priority=1)
            return False
    
    def _get_system_prompt(self) -> str:
        """
        Create a detailed system prompt with context about the robot and its capabilities.
        
        Returns:
            str: System prompt for GPT
        """
        return """
        You are ByteRacer, an AI assistant controlling a small robot car with a camera. You can:
        
        1. Control the robot's movement with two motors (left, right) and a steering servo
        2. Control the camera's pan and tilt servos (like a small head that can look around)
        3. Analyze images from the camera feed
        4. Speak through text-to-speech
        5. Play sound effects
        6. Execute custom Python scripts for complex behaviors
        
        Your hardware capabilities:
        - Two DC motors for driving (speed range: -100 to 100)
        - Direction servo for steering (angle range: -45 to 45 degrees)
        - Camera pan servo (angle range: -90 to 90 degrees)
        - Camera tilt servo (angle range: -35 to 65 degrees)
        - Ultrasonic sensor for distance measurement (front)
        - Line following sensors (bottom)
        
        You must respond with a structured JSON output that contains a list of actions to perform.
        Each action must have a "type" field and additional fields based on the action type:
        
        1. "speak": Use TTS to speak text
           - "text": The text to speak
           
        2. "move": Control the robot's movement
           - "left_speed": Speed of left motor (-100 to 100)
           - "right_speed": Speed of right motor (-100 to 100)
           - "steering_angle": Angle of steering servo (-45 to 45)
           - "duration": How long to maintain this movement in seconds
           
        3. "camera": Control the camera position
           - "pan_angle": Pan angle (-90 to 90)
           - "tilt_angle": Tilt angle (-35 to 65)
           
        4. "play_sound": Play a sound effect
           - "sound_name": Name of the sound file (without extension)
           
        5. "execute_sequence": Execute a sequence of movements
           - "sequence": List of move and camera actions with durations
           
        6. "analyze_image": Analyze the current camera feed and describe what you see
           
        7. "run_script": Create and run a Python script for complex behavior
           - "script_name": Name for the script
           - "script_code": Python code to execute
           - "run_in_background": Whether to run in background
           
        8. "stop_script": Stop a running script
           - "script_name": Name of the script to stop
        
        Example response format:
        {
          "actions": [
            {"type": "speak", "text": "I'm going to dance now!"},
            {"type": "move", "left_speed": 50, "right_speed": 50, "steering_angle": 0, "duration": 1},
            {"type": "camera", "pan_angle": 45, "tilt_angle": 20}
          ]
        }
        
        Be creative, fun, and helpful. For complex behaviors like following objects or dancing,
        use the appropriate action types. Use the camera feed to inform your responses when available.
        """
    
    def _create_messages(self, system_prompt: str, user_prompt: str, image_data: Optional[str] = None) -> List[Dict]:
        """
        Create messages for the OpenAI API, including image if provided.
        
        Args:
            system_prompt: System prompt to provide context
            user_prompt: User command/prompt
            image_data: Base64 encoded image data
            
        Returns:
            List of message dictionaries for the API
        """
        messages = [
            {"role": "system", "content": system_prompt}
        ]
        
        # Create user message, optionally with image
        if image_data:
            user_message = {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}
                    }
                ]
            }
        else:
            user_message = {
                "role": "user",
                "content": user_prompt
            }
        
        messages.append(user_message)
        return messages
    
    async def _get_camera_image(self) -> Optional[str]:
        """
        Capture an image from the camera feed and convert to base64.
        
        Returns:
            str: Base64 encoded image or None if failed
        """
        try:
            # Try to get image from camera stream at 127.0.0.1:9000/mjpg
            response = requests.get("http://127.0.0.1:9000/frame.jpg", timeout=2)
            if response.status_code == 200:
                # Convert to base64
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
    
    async def _call_openai_api(self, messages: List[Dict]) -> Optional[Dict[str, Any]]:
        """
        Call the OpenAI API with the given messages.
        
        Args:
            messages: List of message dictionaries
            
        Returns:
            Dict containing the parsed JSON response or None if failed
        """
        if not self.api_key:
            await self.tts_manager.say("OpenAI API key is not configured. Please set the OPENAI_API_KEY environment variable.", priority=1)
            return None
        
        try:
            # Define response format schema for structured output
            response_format = {
                "type": "json_object",
                "schema": {
                    "type": "object",
                    "properties": {
                        "actions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string"}
                                },
                                "required": ["type"]
                            }
                        }
                    },
                    "required": ["actions"]
                }
            }
            
            # Prepare API request
            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            data = {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "response_format": response_format
            }
            
            # Make API request
            response = requests.post(url, headers=headers, json=data, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            # Extract and parse JSON content
            try:
                content = result["choices"][0]["message"]["content"]
                return json.loads(content)
            except (KeyError, json.JSONDecodeError) as e:
                logger.error(f"Failed to parse API response: {e}")
                logger.error(f"Response content: {result}")
                return None
                
        except Exception as e:
            logger.error(f"Error calling OpenAI API: {e}")
            return None
    
    async def _process_actions(self, response: Dict[str, Any]) -> bool:
        """
        Process the actions from the GPT response.
        
        Args:
            response: Parsed JSON response containing actions
            
        Returns:
            bool: Success status
        """
        if "actions" not in response or not response["actions"]:
            await self.tts_manager.say("I didn't receive any actionable instructions.", priority=1)
            return False
        
        try:
            actions = response["actions"]
            for action in actions:
                action_type = action.get("type", "")
                
                if action_type == "speak":
                    # Handle speech action
                    text = action.get("text", "")
                    if text:
                        await self.tts_manager.say(text, priority=1)
                
                elif action_type == "move":
                    # Handle movement action
                    left_speed = action.get("left_speed", 0)
                    right_speed = action.get("right_speed", 0)
                    steering_angle = action.get("steering_angle", 0)
                    duration = action.get("duration", 1)
                    
                    # Apply constraints
                    left_speed = max(-100, min(100, left_speed))
                    right_speed = max(-100, min(100, right_speed))
                    steering_angle = max(-45, min(45, steering_angle))
                    
                    # Set motor speeds
                    self.px.set_motor_speed(1, left_speed)  # normal motor
                    self.px.set_motor_speed(2, -right_speed)  # reversed motor
                    self.px.set_dir_servo_angle(steering_angle)
                    
                    # Wait for duration
                    await asyncio.sleep(duration)
                    
                    # Stop motors after duration
                    if duration > 0:
                        self.px.set_motor_speed(1, 0)
                        self.px.set_motor_speed(2, 0)
                
                elif action_type == "camera":
                    # Handle camera control action
                    pan_angle = action.get("pan_angle", 0)
                    tilt_angle = action.get("tilt_angle", 0)
                    
                    # Apply constraints
                    pan_angle = max(-90, min(90, pan_angle))
                    tilt_angle = max(-35, min(65, tilt_angle))
                    
                    # Set camera angles
                    self.px.set_cam_pan_angle(pan_angle)
                    self.px.set_cam_tilt_angle(tilt_angle)
                
                elif action_type == "play_sound":
                    # Handle sound playback action
                    sound_name = action.get("sound_name", "")
                    if sound_name:
                        self.sound_manager.play_custom_sound(sound_name)
                
                elif action_type == "execute_sequence":
                    # Handle sequence execution
                    sequence = action.get("sequence", [])
                    for step in sequence:
                        step_type = step.get("type", "")
                        
                        if step_type == "move":
                            left_speed = step.get("left_speed", 0)
                            right_speed = step.get("right_speed", 0)
                            steering_angle = step.get("steering_angle", 0)
                            duration = step.get("duration", 0.5)
                            
                            # Apply constraints
                            left_speed = max(-100, min(100, left_speed))
                            right_speed = max(-100, min(100, right_speed))
                            steering_angle = max(-45, min(45, steering_angle))
                            
                            # Set motor speeds
                            self.px.set_motor_speed(1, left_speed)
                            self.px.set_motor_speed(2, -right_speed)
                            self.px.set_dir_servo_angle(steering_angle)
                            
                            # Wait for duration
                            await asyncio.sleep(duration)
                        
                        elif step_type == "camera":
                            pan_angle = step.get("pan_angle", 0)
                            tilt_angle = step.get("tilt_angle", 0)
                            
                            # Apply constraints
                            pan_angle = max(-90, min(90, pan_angle))
                            tilt_angle = max(-35, min(65, tilt_angle))
                            
                            # Set camera angles
                            self.px.set_cam_pan_angle(pan_angle)
                            self.px.set_cam_tilt_angle(tilt_angle)
                    
                    # Stop motors after sequence
                    self.px.set_motor_speed(1, 0)
                    self.px.set_motor_speed(2, 0)
                
                elif action_type == "analyze_image":
                    # Handle image analysis action
                    image_data = await self._get_camera_image()
                    if image_data:
                        # Create a special prompt for image analysis
                        analysis_prompt = "Describe what you see in this image, focusing on main objects and activities."
                        analysis_messages = self._create_messages("You are an assistant that analyzes images. Describe what you see in detail.", analysis_prompt, image_data)
                        
                        # Call OpenAI API for image analysis
                        analysis_response = await self._call_openai_api(analysis_messages)
                        
                        if analysis_response and "actions" in analysis_response:
                            for analysis_action in analysis_response["actions"]:
                                if analysis_action.get("type") == "speak":
                                    await self.tts_manager.say(analysis_action.get("text", "I can't describe what I see."), priority=1)
                    else:
                        await self.tts_manager.say("I can't access the camera feed right now.", priority=1)
                
                elif action_type == "run_script":
                    # Handle script execution action
                    script_name = action.get("script_name", f"script_{int(time.time())}")
                    script_code = action.get("script_code", "")
                    run_in_background = action.get("run_in_background", False)
                    
                    if script_code:
                        success = await self._run_custom_script(script_name, script_code, run_in_background)
                        if not success:
                            await self.tts_manager.say("I couldn't run the custom script.", priority=1)
                
                elif action_type == "stop_script":
                    # Handle script stopping action
                    script_name = action.get("script_name", "")
                    if script_name and script_name in self.active_processes:
                        self._stop_script(script_name)
                        await self.tts_manager.say(f"Stopped the {script_name} script.", priority=1)
            
            return True
        
        except Exception as e:
            logger.error(f"Error processing actions: {e}")
            logger.error(traceback.format_exc())
            await self.tts_manager.say("I encountered an error while carrying out the actions.", priority=1)
            return False
    
    async def _run_custom_script(self, script_name: str, script_code: str, run_in_background: bool) -> bool:
        """
        Create and run a custom Python script.
        
        Args:
            script_name: Name for the script
            script_code: Python code to execute
            run_in_background: Whether to run in background
            
        Returns:
            bool: Success status
        """
        try:
            # Create script file
            script_path = self.temp_dir / f"{script_name}.py"
            
            # Add imports and helper functions
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

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize robot hardware
px = Picarx()

# Helper functions
def get_camera_frame():
    try:
        response = requests.get("http://127.0.0.1:9000/frame.jpg", timeout=1)
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

# Main script
try:
"""
            
            # Indent the user script code
            indented_code = "\n".join(f"    {line}" for line in script_code.split("\n"))
            
            # Add error handling
            script_footer = """
except KeyboardInterrupt:
    logger.info("Script interrupted by user")
except Exception as e:
    logger.error(f"Script error: {e}")
finally:
    # Clean up
    px.set_motor_speed(1, 0)
    px.set_motor_speed(2, 0)
    px.set_dir_servo_angle(0)
    logger.info("Script ended, motors stopped")
"""
            
            # Write full script to file
            with open(script_path, "w") as f:
                f.write(script_header + indented_code + script_footer)
            
            logger.info(f"Created script at {script_path}")
            
            # Run the script
            if run_in_background:
                # Run in background
                process = subprocess.Popen(
                    ["python3", str(script_path)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                self.active_processes[script_name] = process
                logger.info(f"Running script {script_name} in background, PID: {process.pid}")
                
                # Let the user know
                await self.tts_manager.say(f"Running {script_name} in the background.", priority=1)
                
            else:
                # Run and wait for completion
                await self.tts_manager.say(f"Running {script_name}.", priority=1)
                
                process = await asyncio.create_subprocess_exec(
                    "python3", str(script_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                # Wait for the process to complete
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
        """
        Stop a running script.
        
        Args:
            script_name: Name of the script to stop
            
        Returns:
            bool: Success status
        """
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
        """Clean up resources used by GPTManager"""
        # Stop all running scripts
        for script_name in list(self.active_processes.keys()):
            self._stop_script(script_name)
            
        # Clean up temp files
        for file in self.temp_dir.glob("*.py"):
            try:
                file.unlink()
            except Exception as e:
                logger.error(f"Error removing temp file {file}: {e}")