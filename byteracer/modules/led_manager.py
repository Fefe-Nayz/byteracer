from robot_hat import Pin
import time

class LEDManager:
    def __init__(self, pin: str):
        self.pin = Pin(pin)
        self.pin.value(1)  # Turn on the LED initially

    def turn_on(self):
        self.pin.value(1)  # Turn on the LED

    def turn_off(self):
        self.pin.value(0)  # Turn off the LED

    def toggle(self):
        current_value = self.pin.value()
        self.pin.value(not current_value)  # Toggle the LED state

    def blink(self, times: int, interval: float):
        for _ in range(times):
            self.turn_on()
            time.sleep(interval)
            self.turn_off()
            time.sleep(interval)
    
    