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
import cv2
import numpy as np

logger = logging.getLogger(__name__)

class ScriptCancelledException(Exception):
    """Exception raised when a script is cancelled by user or system."""
    pass

async def _process_audio_commands(audio_queue, tts_manager, sound_manager):
    """
    Process audio commands from the script process and relay them to the main process audio systems.
    This is key to allowing audio playback across process boundaries.

    Args:
        audio_queue: Queue for audio commands from child process
        tts_manager: TTS manager instance from parent process
        sound_manager: Sound manager instance from parent process
    """
    logger.info("Starting audio command processor")
    while True:
        try:
            # Check if there's a command in the queue (non-blocking)
            try:
                command = audio_queue.get_nowait()
            except queue_mod.Empty:
                await asyncio.sleep(0.05)
                continue

            # Process the command based on its type
            if command["type"] == "tts":
                # Text-to-speech request
                text = command.get("text", "")
                priority = command.get("priority", 0)
                lang = command.get("lang")
                logger.debug(f"Audio processor: TTS request: '{text}'")
                await tts_manager.say(text, priority=priority, blocking=False, lang=lang)

            elif command["type"] == "tts_lang":
                # Set TTS language
                lang = command.get("lang")
                if lang:
                    tts_manager.set_language(lang)

            elif command["type"] == "sound":
                # Sound effect request
                sound_type = command.get("sound_type")
                loop = command.get("loop", False)
                name = command.get("name")
                logger.info(f"Audio processor: Sound request: type={sound_type}, name={name}")
                sound_manager.play_sound(sound_type, loop=loop, name=name)

            elif command["type"] == "stop_sound":
                # Stop sound request
                sound_type = command.get("sound_type")
                channel_id = command.get("channel_id")
                sound_manager.stop_sound(sound_type, channel_id)

            elif command["type"] == "alert":
                # Play alert sound
                name = command.get("name")
                sound_manager.play_alert(name)

            elif command["type"] == "custom_sound":
                # Play custom sound
                name = command.get("name")
                sound_manager.play_custom_sound(name)

        except asyncio.CancelledError:
            logger.info("Audio command processor cancelled")
            break
        except Exception as e:
            logger.error(f"Error processing audio command: {e}")
            await asyncio.sleep(0.5)  # Avoid tight loop on error

def _build_script_with_environment(script_code: str) -> str:
    """
    Wraps user code in a function with proper exception handling.
    Automatically indents the user's script properly.
    """
    # Add proper indentation to user code (4 spaces)
    indented_script_lines = []
    for line in script_code.split('\n'):
        if line.strip():  # If not an empty line
            indented_script_lines.append('        ' + line)
        else:
            indented_script_lines.append(line)

    indented_script = '\n'.join(indented_script_lines)

    # Add a simple pass statement if the script is empty to avoid indentation errors
    if not indented_script.strip():
        indented_script = '        pass  # Empty script'

    script_wrapper = f"""
# Generated script wrapper
async def user_script(px, get_camera_image, logger, tts, sound, gpt_manager, result_queue):
    try:
        # Start user code
{indented_script}
        # End user code
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Script error: {{e}}\\n{{tb}}")
        result_queue.put({{"error": str(e), "traceback": tb}})
    finally:
        # Clean up any hardware state
        if hasattr(px, 'motor_speed') and callable(px.motor_speed):
            px.motor_speed(0)  # Stop motors
        if hasattr(px, 'set_dir_servo_angle') and callable(px.set_dir_servo_angle):
            px.set_dir_servo_angle(0)  # Center steering
"""
    return script_wrapper

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
    audio_command_queue = multiprocessing.Queue()  # For TTS and sound requests
    script_result = {"success": False, "error": None, "traceback": None}
    gpt_manager.websocket = websocket
    full_script = _build_script_with_environment(script_code)

    # Start audio request handler task
    audio_task = asyncio.create_task(_process_audio_commands(audio_command_queue, tts_manager, sound_manager))

    def run_script_in_process(result_queue, script_done_event, audio_command_queue):
        try:
            import asyncio
            import threading
            import time
            import json
            import traceback

            # Create proxy classes for TTS and Sound managers
            class TTSProxy:
                def say(self, text, priority=0, blocking=False, lang=None):
                    audio_command_queue.put({"type": "tts", "text": text, "priority": priority, "lang": lang})
                    # For blocking calls, we need to wait a reasonable time
                    if blocking:
                        time.sleep(len(text) * 0.07)  # Rough estimate of TTS duration            
            class SoundProxy:
                def play_sound(self, sound_type, name=None, loop=False):
                    audio_command_queue.put({"type": "sound", "sound_type": sound_type,
                                            "name": name, "loop": loop})
                    return 1  # Fake channel ID

            # Create proxy instances
            tts_proxy = TTSProxy()
            sound_proxy = SoundProxy()

            local_env = {"ScriptCancelledException": ScriptCancelledException,
                         "asyncio": asyncio,
                         "time": time,
                         "json": json,
                         "traceback": traceback,
                         "threading": threading,
                         "cv2": cv2,
                         "np": np}
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            exec(full_script, local_env)
            user_script = local_env.get("user_script")
            if not user_script:
                result_queue.put({"error": "Script compilation failed"})
                return
            loop.run_until_complete(
                user_script(px, get_camera_image, logging.getLogger("script_runner"),
                          tts_proxy, sound_proxy, gpt_manager, result_queue)
            )
            result_queue.put({"success": True})
        except ScriptCancelledException as e:
            result_queue.put({"cancelled": str(e)})
        except Exception as e:
            tb = traceback.format_exc()
            result_queue.put({"error": str(e), "traceback": tb})
        finally:
            script_done_event.set()

    # Launch process with audio_command_queue
    process = multiprocessing.Process(target=run_script_in_process,
                                     args=(result_queue, script_done_event, audio_command_queue))
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

    # If we need to cancel the process
    if process.is_alive():
        if gpt_manager.gpt_command_cancelled:
            logger.info(f"Cancelling script '{script_name}' due to user request")
            script_result["error"] = "Script cancelled by user"
            if websocket and hasattr(gpt_manager, "_send_gpt_status_update"):
                await gpt_manager._send_gpt_status_update(websocket, "cancelled", "Script cancelled by user")
        else:
            # Timeout or other issue
            logger.warning(f"Script '{script_name}' timeout or unexpected state")
            script_result["error"] = "Script execution timed out or encountered an issue"
            if websocket and hasattr(gpt_manager, "_send_gpt_status_update"):
                await gpt_manager._send_gpt_status_update(websocket, "error", "Script timed out or encountered an issue")

        # Force kill child process
        if script_name in gpt_manager.active_processes:
            try:
                # Instead of using multiprocessing API, use OS signals for reliable termination
                os.kill(process.pid, signal.SIGTERM)
                process.join(1.0)  # Give it a second to shut down
                if process.is_alive():  # If still alive, force kill
                    os.kill(process.pid, signal.SIGKILL)
            except Exception as e:
                logger.error(f"Error terminating script process: {e}")

    # Clean up process tracking
    if script_name in gpt_manager.active_processes:
        del gpt_manager.active_processes[script_name]

    # Reset hardware state again from parent to be extra sure
    # This is important in case the child process didn't clean up properly
    try:
        if hasattr(px, 'motor_speed') and callable(px.motor_speed):
            px.motor_speed(0)
        if hasattr(px, 'set_dir_servo_angle') and callable(px.set_dir_servo_angle):
            px.set_dir_servo_angle(0)
    except Exception as e:
        logger.error(f"Error resetting hardware after script: {e}")

    # Clean up the audio task
    audio_task.cancel()
    try:
        await audio_task
    except asyncio.CancelledError:
        pass

    # Process will be cleaned up by Python's garbage collector
    return script_result["success"], script_result

async def check_script_for_issues(script_code: str) -> dict:
    """
    Check a script for common issues and problematic patterns.

    Args:
        script_code: The Python code to check

    Returns:
        dict: Issues found in the script
    """
    issues = []

    # Check for potentially dangerous imports
    dangerous_imports = [
        "os.system", "subprocess", "pty", "popen",
        "eval(", "exec(", "__import__",
        "shutil.rmtree", "os.remove", "unlink",
    ]

    for item in dangerous_imports:
        if item in script_code:
            issues.append(f"Script contains potentially dangerous code: '{item}'")

    # Check for infinite loops without sleep/delay
    if "while True" in script_code and "await asyncio.sleep" not in script_code:
        issues.append("Script contains 'while True' without 'await asyncio.sleep()', may cause CPU overuse")

    return {"issues": issues}