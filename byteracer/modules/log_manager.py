import os
import logging
import time
from datetime import datetime
from pathlib import Path
import asyncio
import threading
import json
import websockets
from logging.handlers import QueueHandler, QueueListener
import queue
import sys
from collections import deque

class ColoredFormatter(logging.Formatter):
    """
    A custom formatter that adds color to logs when displayed in the console.
    """
    # ANSI color codes
    GREY = "\x1b[38;20m"
    GREEN = "\x1b[32;20m"
    YELLOW = "\x1b[33;20m"
    RED = "\x1b[31;20m"
    BOLD_RED = "\x1b[31;1m"
    BLUE = "\x1b[34;20m"
    MAGENTA = "\x1b[35;20m"
    CYAN = "\x1b[36;20m"
    RESET = "\x1b[0m"
    
    def __init__(self, fmt=None, datefmt=None, style='%'):
        super().__init__(fmt, datefmt, style)
        self.fmt = fmt or '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        self.datefmt = datefmt or '%Y-%m-%d %H:%M:%S'
        
        # Define custom formats for each log level with colors
        self.FORMATS = {
            logging.DEBUG: self.GREY + self.fmt + self.RESET,
            logging.INFO: self.GREEN + self.fmt + self.RESET,
            logging.WARNING: self.YELLOW + self.fmt + self.RESET,
            logging.ERROR: self.RED + self.fmt + self.RESET,
            logging.CRITICAL: self.BOLD_RED + self.fmt + self.RESET
        }
    
    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, self.datefmt)
        return formatter.format(record)


class WebSocketLogHandler(logging.Handler):
    """
    A logging handler that sends logs to a WebSocket connection.
    """
    def __init__(self, websocket=None):
        super().__init__()
        self.websocket = websocket
        # Use a thread-safe queue instead of asyncio.Queue
        self.queue = queue.Queue(maxsize=500)
        self.event_loop = None
        self.worker_thread = None
        self.running = True
        self.backlog = deque(maxlen=500)
        # Start the worker thread
        self._start_worker()
        
    def _start_worker(self):
        """Start the worker thread that processes logs"""
        if not self.worker_thread or not self.worker_thread.is_alive():
            self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
            self.worker_thread.start()
        
    def set_websocket(self, websocket):
        """Update the WebSocket connection"""
        self.websocket = websocket
        # Store a reference to the event loop when the WebSocket is set
        self.event_loop = asyncio.get_running_loop()
        # Replay recent logs so the UI can see messages produced before the
        # browser connected, including startup and maintenance script logs.
        for log_data in list(self.backlog):
            try:
                self.queue.put_nowait(log_data)
            except queue.Full:
                break
        
    def emit(self, record):
        """Put log record in the queue for sending - safe to call from any thread"""
        if not self.running:
            return
            
        try:
            log_entry = self.format(record)
            
            log_data = {
                "level": record.levelname,
                "message": log_entry,
                "timestamp": int(time.time() * 1000)
            }

            self.backlog.append(log_data)

            # Add to thread-safe queue - no asyncio needed here.
            # Drop live streaming entries if the UI is not consuming fast enough.
            self.queue.put_nowait(log_data)
            
        except queue.Full:
            pass
        except Exception as e:
            self.handleError(record)
    
    def _process_queue(self):
        """Thread method that processes the queue and sends to the WebSocket via the event loop"""
        while self.running:
            try:
                # Get next log with a timeout
                try:
                    log_data = self.queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                
                # Skip if we don't have an event loop or websocket yet
                if not self.event_loop or not self.websocket:
                    self.queue.task_done()
                    time.sleep(0.1)
                    continue
                
                # Create message
                message = json.dumps({
                    "name": "log_message",
                    "data": log_data,
                    "createdAt": int(time.time() * 1000)
                })
                
                # Schedule sending on the event loop
                if self.event_loop and self.websocket and not self.event_loop.is_closed():
                    asyncio.run_coroutine_threadsafe(self._send_log(message), self.event_loop)
                
                # Mark task as complete in the queue
                self.queue.task_done()
                
            except Exception as e:
                print(f"Error in WebSocket log worker: {e}")
                time.sleep(1)  # Prevent tight loop on error
            
    async def _send_log(self, message):
        """Coroutine to send a single log message via WebSocket"""
        if not self.websocket:
            return

        try:
            await self.websocket.send(message)
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            print(f"Error sending log via WebSocket: {e}")
                
    def close(self):
        """Close the handler"""
        self.running = False
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=1.0)  # Wait for worker thread to finish
        super().close()

class LogManager:
    """
    Manages logging with timestamps and automatic log rotation.
    """
    def __init__(self, log_dir=None, max_log_files=5, max_log_size_mb=2):
        # Set log directory
        if log_dir is None:
            # Default to tmpfs-friendly logs. Set BYTERACER_LOG_DIR to persist logs elsewhere.
            self.log_dir = Path(os.environ.get("BYTERACER_LOG_DIR", "/tmp/byteracer/logs"))
        else:
            self.log_dir = Path(log_dir)
        
        # Ensure log directory exists
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Log settings
        self.max_log_files = max_log_files
        self.max_log_size_mb = max_log_size_mb
        self.file_log_level = getattr(
            logging,
            os.environ.get("BYTERACER_FILE_LOG_LEVEL", "INFO").upper(),
            logging.INFO,
        )
        self.log_file_path = self.log_dir / f"byteracer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        
        # WebSocket handler
        self.websocket_handler = None
        
        # Configure root logger
        self._setup_logging()
        
        # Log maintenance task
        self._cleanup_task = None
        self._external_log_task = None
        self._external_log_positions = {}
        self._tail_start_time = time.time()
        self._running = True
        
        # Initial log
        logging.info("Log Manager initialized")
    def _setup_logging(self):
        """Set up the logging configuration"""
        # Create a root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        
        # Clear existing handlers
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # Create file handler
        file_handler = logging.FileHandler(self.log_file_path)
        file_handler.setLevel(self.file_log_level)
        
        # Create console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # Create standard formatter with timestamp (for file logging)
        standard_format = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        standard_datefmt = '%Y-%m-%d %H:%M:%S'
        standard_formatter = logging.Formatter(standard_format, datefmt=standard_datefmt)
        
        # Create colored formatter (for console output)
        colored_formatter = ColoredFormatter(fmt=standard_format, datefmt=standard_datefmt)
        
        # Create WebSocket handler
        self.websocket_handler = WebSocketLogHandler()
        self.websocket_handler.setLevel(logging.INFO)
        self.websocket_handler.setFormatter(standard_formatter)
        
        # Set formatters - standard for file, colored for console
        file_handler.setFormatter(standard_formatter)
        console_handler.setFormatter(colored_formatter)
        
        # Add handlers to root logger
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)
        root_logger.addHandler(self.websocket_handler)
        
        # Reduce verbosity of specific third-party libraries
        logging.getLogger('picamera2').setLevel(logging.INFO)
        logging.getLogger('picamera2.picamera2').setLevel(logging.INFO)
        logging.getLogger('vilib').setLevel(logging.INFO)
        
        # Initial log message
        logging.info(f"Logging to {self.log_file_path}")
    
    def set_websocket(self, websocket):
        """Set the WebSocket connection for log streaming"""
        if self.websocket_handler:
            self.websocket_handler.set_websocket(websocket)
            logging.info("WebSocket log streaming enabled")
    
    async def start(self):
        """Start the log maintenance task"""
        self._cleanup_task = asyncio.create_task(self._log_maintenance())
        self._external_log_task = asyncio.create_task(self._tail_external_logs())
        logging.info("Log maintenance task started")
    
    async def stop(self, close_handlers=False):
        """Stop the log maintenance task"""
        self._running = False
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        if self._external_log_task:
            self._external_log_task.cancel()
            try:
                await self._external_log_task
            except asyncio.CancelledError:
                pass
        
        # Close WebSocket handler
        if self.websocket_handler:
            self.websocket_handler.close()

        logging.info("Log Manager stopped")

        if close_handlers:
            self._close_handlers()

    def _close_handlers(self):
        """Detach and close root logger handlers owned by this manager."""
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
    
    async def _log_maintenance(self):
        """Periodically check log files and clean up if needed"""
        logging.info("Starting log maintenance task")
        
        while self._running:
            try:
                # Check current log file size
                await self._check_log_size()
                
                # Clean up old log files
                await self._clean_old_logs()
                
                # Run maintenance every hour
                await asyncio.sleep(3600)
                
            except asyncio.CancelledError:
                logging.info("Log maintenance task cancelled")
                break
            except Exception as e:
                logging.error(f"Error in log maintenance: {e}")
                await asyncio.sleep(60)  # Retry after a minute

    async def _tail_external_logs(self):
        """Stream maintenance shell script logs into the normal Python log flow."""
        logging.info("Starting external script log tailer")

        while self._running:
            try:
                self._emit_new_external_log_lines()
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                logging.info("External script log tailer cancelled")
                break
            except Exception as e:
                logging.error(f"Error tailing external logs: {e}")
                await asyncio.sleep(5)

    def _iter_external_log_files(self):
        """Return shell-maintenance log files without tailing our own byteracer log."""
        try:
            for path in self.log_dir.glob("*.log"):
                if path.name.startswith("byteracer_"):
                    continue
                if path.is_file():
                    yield path
        except Exception as e:
            logging.error(f"Error listing external logs: {e}")

    def _emit_new_external_log_lines(self):
        for path in self._iter_external_log_files():
            try:
                stat = path.stat()
                key = str(path)
                previous_position = self._external_log_positions.get(key)

                if previous_position is None:
                    # Avoid flooding the UI with stale historical logs, but keep
                    # recent boot/script lines that may have happened before the
                    # browser connected.
                    if stat.st_mtime >= self._tail_start_time - 10:
                        position = max(0, stat.st_size - 16384)
                    else:
                        position = stat.st_size
                elif stat.st_size < previous_position:
                    position = 0
                else:
                    position = previous_position

                if stat.st_size <= position:
                    self._external_log_positions[key] = stat.st_size
                    continue

                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    handle.seek(position)
                    chunk = handle.read(65536)
                    new_position = handle.tell()

                self._external_log_positions[key] = new_position

                lines = chunk.splitlines()
                if position > 0 and lines:
                    # The first line may be partial when we start from a tail
                    # offset inside a large file.
                    lines = lines[1:]

                script_logger = logging.getLogger(f"scripts.{path.stem}")
                for line in lines[-200:]:
                    cleaned_line = line.strip()
                    if not cleaned_line:
                        continue
                    script_logger.log(self._infer_external_log_level(cleaned_line), cleaned_line)

            except FileNotFoundError:
                self._external_log_positions.pop(str(path), None)
            except Exception as e:
                logging.error(f"Error reading external log {path}: {e}")

    @staticmethod
    def _infer_external_log_level(line):
        upper = line.upper()
        if "CRITICAL" in upper or "FATAL" in upper:
            return logging.CRITICAL
        if "ERROR" in upper or "FAILED" in upper or "EXIT 1" in upper:
            return logging.ERROR
        if "WARNING" in upper or "WARN" in upper:
            return logging.WARNING
        return logging.INFO
    
    async def _check_log_size(self):
        """Check if current log file needs rotation"""
        try:
            if self.log_file_path.exists():
                size_mb = self.log_file_path.stat().st_size / (1024 * 1024)
                
                if size_mb >= self.max_log_size_mb:
                    # Create a new log file
                    logging.info(f"Log file size ({size_mb:.2f} MB) exceeded limit. Rotating...")
                    
                    # Create a new file handler with a new log file
                    new_log_path = self.log_dir / f"byteracer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
                    
                    # Update the FileHandler in root logger
                    root_logger = logging.getLogger()
                    
                    # Find and replace the file handler
                    for handler in root_logger.handlers[:]:
                        if isinstance(handler, logging.FileHandler):
                            # Get the formatter
                            formatter = handler.formatter
                            
                            # Remove old handler
                            root_logger.removeHandler(handler)
                            handler.close()
                            
                            # Create new handler
                            new_handler = logging.FileHandler(new_log_path)
                            new_handler.setLevel(self.file_log_level)
                            new_handler.setFormatter(formatter)
                            
                            # Add new handler
                            root_logger.addHandler(new_handler)
                            
                            # Update log file path
                            self.log_file_path = new_log_path
                            logging.info(f"Rotated log file to {new_log_path}")
                            break
        except Exception as e:
            logging.error(f"Error checking log size: {e}")
    
    async def _clean_old_logs(self):
        """Remove old log files if there are too many"""
        try:
            # List all log files
            log_files = list(self.log_dir.glob("byteracer_*.log"))
            
            # Sort by modification time (oldest first)
            log_files.sort(key=lambda x: x.stat().st_mtime)
            
            # If we have too many logs, delete the oldest ones
            while len(log_files) > self.max_log_files:
                file_to_delete = log_files.pop(0)  # Get the oldest
                
                try:
                    file_to_delete.unlink()
                    logging.info(f"Deleted old log file: {file_to_delete}")
                except Exception as e:
                    logging.error(f"Error deleting old log file {file_to_delete}: {e}")
        
        except Exception as e:
            logging.error(f"Error cleaning old logs: {e}")
    
    def get_log_list(self):
        """
        Return a list of available log files.
        
        Returns:
            list: List of dictionaries with log file information
        """
        logs = []
        
        try:
            # List all log files
            log_files = list(self.log_dir.glob("byteracer_*.log"))
            
            for log_file in log_files:
                # Get file stats
                stat = log_file.stat()
                
                logs.append({
                    "name": log_file.name,
                    "path": str(log_file),
                    "size": stat.st_size,
                    "created": datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S'),
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                })
            
            # Sort by modification time (newest first)
            logs.sort(key=lambda x: x["modified"], reverse=True)
            
        except Exception as e:
            logging.error(f"Error getting log list: {e}")
        
        return logs
    
    def get_log_content(self, log_name=None, max_lines=100):
        """
        Get content from a specific log file or the current log.
        
        Args:
            log_name (str): Name of the log file to read, or None for current log
            max_lines (int): Maximum number of lines to read from the end
            
        Returns:
            str: Log content or error message
        """
        try:
            # Determine which log file to read
            if log_name:
                log_path = self.log_dir / log_name
                if not log_path.exists() or not log_path.is_file():
                    return f"Log file not found: {log_name}"
            else:
                log_path = self.log_file_path
            
            # Read the last N lines (this is not the most efficient way for very large files,
            # but should be fine for typical log files)
            with open(log_path, 'r') as f:
                lines = f.readlines()
                return ''.join(lines[-max_lines:])
            
        except Exception as e:
            error_msg = f"Error reading log file: {e}"
            logging.error(error_msg)
            return error_msg
