#!/usr/bin/env python3
"""
Standalone TTS script for system notifications.
This script can be called from bash scripts to provide vocal feedback.
"""
import sys
import argparse
from robot_hat import TTS
import time

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Text-to-Speech for ByteRacer')
    parser.add_argument('text', help='Text to speak', nargs='?')
    parser.add_argument('-f', '--file', help='File to read text from')
    parser.add_argument('-l', '--lang', help='Language for TTS (default: en-US)', default='en-US')
    
    args = parser.parse_args()
    
    # Initialize TTS
    tts = TTS()
    
    # Check if the requested language is supported
    supported_langs = tts.supported_lang()
    if args.lang not in supported_langs:
        print(f"Error: Language '{args.lang}' is not supported.", file=sys.stderr)
        print(f"Supported languages: {', '.join(supported_langs)}", file=sys.stderr)
        return 1
    
    # Set language properly
    try:
        tts.lang(args.lang)
    except ValueError as e:
        print(f"Error setting language: {e}", file=sys.stderr)
        return 1
    
    # Get text from file or command line
    if args.file:
        try:
            with open(args.file, 'r') as f:
                text = f.read().strip()
        except Exception as e:
            print(f"Error reading file: {e}", file=sys.stderr)
            return 1
    elif args.text:
        text = args.text
    else:
        parser.print_help()
        return 1
    
    # Speak the text
    try:
        print(f"Speaking: {text}")
        tts.say(text)
        return 0
    except Exception as e:
        print(f"TTS error: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())