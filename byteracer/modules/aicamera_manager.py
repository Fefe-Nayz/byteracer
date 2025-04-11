import asyncio
import time
import logging
import threading
import numpy as np
from enum import Enum, auto
from vilib import Vilib
from picamera2 import Picamera2

logger = logging.getLogger(__name__)

class AICameraCameraManager:
    """
    Manages the camera ai capabilities
    """
    def __init__(self):
        # init logic
        logger.info("AI CAMERA INITIALIZED")
        return True
    #def ...