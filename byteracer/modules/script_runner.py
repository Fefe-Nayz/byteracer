"""
Script execution environment for safely running ChatGPT-generated code.
Provides isolation, cancellation support, and error reporting.
"""

import asyncio
import threading
import logging
import traceback
import time
import json
from typing import Dict, Any, Optional, Callable

logger = logging.getLogger(__name__)

class ScriptCancelledException(Exception):
    """Raised when a script is cancelled by user request."""
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
) -> bool:
    """
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
    """
    import concurrent.futures
    
    # Create a unique script name based on timestamp
    script_name = f"script_{int(time.time())}"
    
    # Create threading event for script completion signaling
    script_done_event = threading.Event()
    script_result = {"success": False, "error": None}
    
    # Store the websocket for error reporting
    gpt_manager.websocket = websocket
    
    # Prepare the script with our execution environment
    full_script = _build_script_with_environment(script_code)
    
    # Local namespace for script execution
    local_env = {"ScriptCancelledException": ScriptCancelledException,
    "asyncio": asyncio,
    "time": time,
    "json": json,
    "traceback": traceback,
    "threading": threading
    }
    
    # Function to run in separate thread
    def run_script_in_thread():
        try:
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Execute the script to define the user_script function
            exec(full_script, local_env)
            
            # Get the defined function and run it
            user_script = local_env.get("user_script")
            if not user_script:
                logger.error("Failed to compile user script - user_script function not defined")
                script_result["error"] = "Script compilation failed"
                return
                
            # Run the script with provided resources
            loop.run_until_complete(
                user_script(px, get_camera_image, logger, tts_manager, sound_manager, gpt_manager)
            )
            script_result["success"] = True
        except ScriptCancelledException as e:
            logger.info(f"Script cancelled: {e}")
            script_result["error"] = str(e)
            if websocket and hasattr(gpt_manager, "_send_gpt_status_update"):
                coro = gpt_manager._send_gpt_status_update(websocket, "cancelled", str(e))
                asyncio.run_coroutine_threadsafe(coro, asyncio.get_event_loop())
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"Error in script execution: {e}\n{tb}")
            script_result["error"] = str(e)
            if websocket and hasattr(gpt_manager, "_send_gpt_status_update"):
                coro = gpt_manager._send_gpt_status_update(websocket, "error", f"Script error: {e}", {"traceback": tb})
                asyncio.run_coroutine_threadsafe(coro, asyncio.get_event_loop())
        finally:
            # Ensure motors are stopped
            try:
                px.set_motor_speed(1, 0)  # rear_left
                px.set_motor_speed(2, 0)  # rear_right
                px.set_dir_servo_angle(0)  # steering
                px.set_cam_pan_angle(0)    # camera pan
                px.set_cam_tilt_angle(0)   # camera tilt
            except Exception as shutdown_e:
                logger.error(f"Error stopping motors: {shutdown_e}")
                
            # Signal that we're done
            script_done_event.set()
    
    try:
        # Create thread pool for execution
        with concurrent.futures.ThreadPoolExecutor() as executor:
            if run_in_background:
                # Run script in background thread
                future = executor.submit(run_script_in_thread)
                
                # Store references for later cancellation
                thread_info = {
                    'future': future,
                    'done_event': script_done_event
                }
                gpt_manager.active_processes[script_name] = thread_info
                logger.info(f"Running script '{script_name}' in background")
                return True
            else:
            # Run in thread but wait for completion
                logger.info(f"Running script '{script_name}' and waiting for completion")
                future = executor.submit(run_script_in_thread)
                thread_info = {
                    'future': future,
                    'done_event': script_done_event,
                    'thread': threading.current_thread()
                }
                
                # Store reference for potential cancellation later
                gpt_manager.active_processes[script_name] = thread_info
                while not script_done_event.is_set() and not gpt_manager.gpt_command_cancelled:
                    await asyncio.sleep(0.1)
                
                # Handle cancellation
                if gpt_manager.gpt_command_cancelled and not script_done_event.is_set():
                    logger.info(f"Script '{script_name}' execution cancelled")
                    # Wait briefly for thread cleanup
                    script_done_event.wait(timeout=3.0)
                
                return script_result["success"]
    except Exception as e:
        logger.error(f"Error setting up script execution: {e}")
        if websocket:
            await _send_error_to_websocket(
                websocket, 
                "ScriptSetupError", 
                f"Failed to set up script execution: {e}"
            )
        return False

def _build_script_with_environment(script_code: str) -> str:
    """
    Builds a complete script with proper environment setup, error handling,
    and resource safety mechanisms.
    
    Args:
        script_code: The user's Python code
        
    Returns:
        str: Complete script with execution environment
    """
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
        "async def user_script(px, get_camera_image, logger, tts, sound, gpt_manager):\n"
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
        "    except asyncio.CancelledError:\n"
        "        logger.info('Script task cancelled')\n"
        "    except Exception as e:\n"
        "        tb = traceback.format_exc()\n"
        "        logger.error(f'Script error: {e}\\n{tb}')\n"
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

async def _send_error_to_websocket(websocket, error_type: str, message: str, traceback_str: str = None):
    """
    Sends script execution errors to the websocket client.
    
    Args:
        websocket: The websocket connection
        error_type: Type of error
        message: Error message
        traceback_str: Optional traceback string
    """
    try:
        error_data = {
            "name": "script_error",
            "data": {
                "error_type": error_type,
                "message": message,
                "traceback": traceback_str if traceback_str else "",
                "timestamp": int(time.time() * 1000)
            },
            "createdAt": int(time.time() * 1000)
        }
        await websocket.send(json.dumps(error_data))
    except Exception as e:
        logger.error(f"Failed to send error to websocket: {e}")
