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

class WebSocketLogHandler(logging.Handler):
    """
    A logging handler that sends logs to a WebSocket connection.
    """
    def __init__(self, websocket=None):
        super().__init__()
        self.websocket = websocket
        # Use a thread-safe queue instead of asyncio.Queue
        self.queue = queue.Queue()
        self.event_loop = None
        self.worker_thread = None
        self.running = True
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
        
    def emit(self, record):
        """Put log record in the queue for sending - safe to call from any thread"""
        if not self.running:
            return
            
        try:
            log_entry = self.format(record)
            
            # Add to thread-safe queue - no asyncio needed here
            self.queue.put({
                "level": record.levelname,
                "message": log_entry,
                "timestamp": int(time.time() * 1000)
            })
            
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
        if self.websocket and hasattr(self.websocket, 'open') and self.websocket.open:
            try:
                await self.websocket.send(message)
            except websockets.exceptions.ConnectionClosed:
                pass  # Connection closed
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
    def __init__(self, log_dir=None, max_log_files=10, max_log_size_mb=10):
        # Set log directory
        if log_dir is None:
            # Default to logs directory in the project
            self.log_dir = Path(__file__).parent.parent / "logs"
        else:
            self.log_dir = Path(log_dir)
        
        # Ensure log directory exists
        self.log_dir.mkdir(exist_ok=True)
        
        # Log settings
        self.max_log_files = max_log_files
        self.max_log_size_mb = max_log_size_mb
        self.log_file_path = self.log_dir / f"byteracer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        
        # WebSocket handler
        self.websocket_handler = None
        
        # Configure root logger
        self._setup_logging()
        
        # Log maintenance task
        self._cleanup_task = None
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
        file_handler.setLevel(logging.DEBUG)
        
        # Create console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # Create formatter with timestamp
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Create WebSocket handler
        self.websocket_handler = WebSocketLogHandler()
        self.websocket_handler.setLevel(logging.INFO)
        self.websocket_handler.setFormatter(formatter)
        
        # Set formatters
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
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
        logging.info("Log maintenance task started")
    
    async def stop(self):
        """Stop the log maintenance task"""
        self._running = False
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Close WebSocket handler
        if self.websocket_handler:
            self.websocket_handler.close()
        
        logging.info("Log Manager stopped")
    
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
                            new_handler.setLevel(logging.DEBUG)
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