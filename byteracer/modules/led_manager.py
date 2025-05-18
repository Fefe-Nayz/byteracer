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
        self.led_state = 1  # Track LED state internally (1 = on, 0 = off)
        
        if self.enabled:
            self.turn_on()  # Turn on the LED initially
        else:
            self.turn_off()

    def turn_on(self):
        if not self.enabled:
            return
        self.pin.value(1)  # Turn on the LED
        self.led_state = 1  # Update internal state

    def turn_off(self):
        self.pin.value(0)  # Turn off the LED
        self.led_state = 0  # Update internal state

    def toggle(self):
        if self.led_state == 1:
            self.turn_off()
        else:
            self.turn_on()

    def blink(self, times: int, interval: float):
        """
        Blink LED a specific number of times (blocking).
        
        Args:
            times (int): Number of times to blink
            interval (float): Time between on and off states in seconds
        """
        if not self.enabled:
            return
        previous_state = self.led_state  # Store current state before blinking
        for _ in range(times):
            self.turn_on()
            time.sleep(interval)
            self.turn_off()
            time.sleep(interval)
        
        # Restore previous state after blinking
        if previous_state == 1:
            self.turn_on()
        else:
            self.turn_off()
        

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
            
        # Store the current LED state before blinking
        self.previous_state = self.led_state
            
        # Stop any existing blinking
        self.stop_blinking()
          # Start new blinking thread
        self.blink_active = True
        self.blink_interval = interval
        self.blink_thread = threading.Thread(target=self._blink_loop, args=(interval,), daemon=True)
        self.blink_thread.start()
        
    def stop_blinking(self, led_on: bool = True):
        """Stop any active continuous blinking and ensure the LED is on if enabled."""
        self.blink_active = False
        
        # Wait for the thread to end if it exists
        if self.blink_thread and self.blink_thread.is_alive():
            self.blink_thread.join(timeout=1.0)
            
        self.blink_thread = None
        
        # Always turn on the LED if enabled
        if self.enabled and led_on:
            self.turn_on()
        else:
            self.turn_off()
    
    def set_enabled(self, enabled: bool):
        """
        Enable or disable the LED.
        
        Args:
            enabled (bool): Whether the LED should be enabled
        """
        self.enabled = enabled
        if enabled:
            self.turn_on()
        else:
            self.turn_off()
            # Stop blinking if it was active
            if self.blink_active:
                self.stop_blinking()