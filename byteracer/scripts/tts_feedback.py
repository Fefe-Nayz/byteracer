#!/usr/bin/env python3
import sys
from robot_hat import TTS

def main():
    if len(sys.argv) < 2:
        print("No text provided for TTS. Usage: tts_feedback.py <text to say>")
        return
    text = " ".join(sys.argv[1:])
    tts = TTS()
    tts.lang("fr-FR")  # French TTS
    tts.say(text)

if __name__ == "__main__":
    main()
