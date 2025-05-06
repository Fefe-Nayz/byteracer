from robot_hat import Pin
import time
import threading

class LEDManager:
    def __init__(self, pin: str, config_manager):
        self.config_manager = config_manager
        self.enabled = self.config_manager.get("led.enabled")  # Check if LED is enabled in the config
        self.pin = Pin(pin)
        self.blink_thread = None
        self.blink_active = False
        self.blink_interval = 0.5  # Default interval
        
        if self.enabled:
            self.pin.value(1)  # Turn on the LED initially
        else:
            self.pin.value(0)

    def turn_on(self):
        if not self.enabled:
            return
        self.pin.value(1)  # Turn on the LED

    def turn_off(self):
        self.pin.value(0)  # Turn off the LED

    def toggle(self):
        current_value = self.pin.value()
        self.pin.value(not current_value)  # Toggle the LED state

    def blink(self, times: int, interval: float):
        """
        Blink LED a specific number of times (blocking).
        
        Args:
            times (int): Number of times to blink
            interval (float): Time between on and off states in seconds
        """
        if not self.enabled:
            return
        for _ in range(times):
            self.turn_on()
            time.sleep(interval)
            self.turn_off()
            time.sleep(interval)

    def _blink_loop(self, interval: float):
        """
        Internal function to run the blinking loop in a separate thread.
        
        Args:
            interval (float): Time between on and off states in seconds
        """
        while self.blink_active and self.enabled:
            self.turn_on()
            time.sleep(interval)
            self.turn_off()
            time.sleep(interval)

    def start_blinking(self, interval: float = 0.5):
        """
        Start continuous LED blinking in a separate thread (non-blocking).
        
        Args:
            interval (float, optional): Time between on and off states in seconds. Defaults to 0.5.
        """
        if not self.enabled:
            return
            
        # Stop any existing blinking
        self.stop_blinking()
        
        # Start new blinking thread
        self.blink_active = True
        self.blink_interval = interval
        self.blink_thread = threading.Thread(target=self._blink_loop, args=(interval,), daemon=True)
        self.blink_thread.start()
        
    def stop_blinking(self):
        """Stop any active continuous blinking and turn off the LED."""
        self.blink_active = False
        
        # Wait for the thread to end if it exists
        if self.blink_thread and self.blink_thread.is_alive():
            self.blink_thread.join(timeout=1.0)
            
        self.blink_thread = None
        self.turn_off()
    
    def set_enabled(self, enabled: bool):
        """
        Enable or disable the LED.
        
        Args:
            enabled (bool): Whether the LED should be enabled
        """
        self.enabled = enabled
        if enabled:
            self.pin.value(1)
        else:
            self.pin.value(0)
            # Stop blinking if it was active
            if self.blink_active:
                self.stop_blinking()