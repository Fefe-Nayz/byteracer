"""
Script execution environment for safely running ChatGPT-generated code.
Provides isolation, cancellation support, and error reporting.
"""

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
) -> tuple[bool, dict|None]:
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
                user_script(px, get_camera_image, logging.getLogger("script_runner"), tts_manager, sound_manager, gpt_manager)
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
