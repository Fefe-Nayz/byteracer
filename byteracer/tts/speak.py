#!/usr/bin/env python3
"""
Standalone TTS script for system notifications.
This script can be called from bash scripts to provide vocal feedback.
"""
import sys
import argparse
import os
import uuid
import subprocess
import time
from pathlib import Path

# Add parent directory to path to import modules from the byteracer package
sys.path.append(str(Path(__file__).resolve().parent.parent))
try:
    from modules.config_manager import ConfigManager
except ImportError:
    # Fallback if modules can't be imported
    ConfigManager = None

def main():
    # Try to get config settings
    config_volume = None
    if ConfigManager is not None:
        try:
            config = ConfigManager()
            # Use system_tts_volume by default for system notifications
            config_volume = config.get("sound.system_tts_volume")
            is_enabled = config.get("sound.tts_enabled")
            if not is_enabled:
                config_volume = 0
        except Exception as e:
            print(f"Warning: Could not load config settings: {e}", file=sys.stderr)
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Text-to-Speech for ByteRacer')
    parser.add_argument('text', help='Text to speak', nargs='?')
    parser.add_argument('-f', '--file', help='File to read text from')
    parser.add_argument('-l', '--lang', help='Language for TTS (default: en-US)', default='en-US')
    parser.add_argument('-v', '--volume', help='Volume level 0-100 (default: from config or 100)', 
                       type=int, default=config_volume if config_volume is not None else 100)
    
    args = parser.parse_args()
    
    # Get supported languages (using robot_hat's functions)
    supported_langs = [
        'en-US', 'en-GB', 'de-DE', 'es-ES', 'fr-FR', 'it-IT'
    ]
    
    # Check if the requested language is supported
    if args.lang not in supported_langs:
        print(f"Error: Language '{args.lang}' is not supported.", file=sys.stderr)
        print(f"Supported languages: {', '.join(supported_langs)}", file=sys.stderr)
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
    
    # Validate volume
    volume = max(0, min(100, args.volume))
    
    # Create a unique temp file name to prevent conflicts
    temp_file = f"/tmp/tts_startup_{uuid.uuid4().hex}.wav"
    volume_file = None

    
    try:
        # Speak the text using direct commands instead of robot_hat
        print(f"Speaking: {text} (volume: {volume}%)")
        
        # Generate wave file with pico2wave
        pico_cmd = f'pico2wave -l {args.lang} -w {temp_file} "{text}"'
        result = subprocess.run(pico_cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"TTS error: {result.stderr}", file=sys.stderr)
            return 1
        
        # Apply volume adjustment if needed
        if volume != 100:
            # Calculate volume multiplier (0-1 range for sox)
            vol_multiplier = max(0.0, min(1.0, volume / 100.0))
            
            # Create a new temporary file with adjusted volume
            volume_file = f"/tmp/tts_vol_{uuid.uuid4().hex}.wav"
            
            # Use sox to adjust volume (create a new file instead of playing directly)
            vol_cmd = f'sox {temp_file} {volume_file} vol {vol_multiplier}'
            print(f"Adjusting volume with sox: multiplier {vol_multiplier}")
            
            vol_result = subprocess.run(vol_cmd, shell=True, capture_output=True, text=True)
            if vol_result.returncode != 0:
                print(f"Volume adjustment error: {vol_result.stderr}", file=sys.stderr)
                # If volume adjustment fails, fall back to the original file
                play_cmd = f'aplay {temp_file}'
            else:
                # Play the volume-adjusted file
                play_cmd = f'aplay {volume_file}'
                
                # Remove the original temp file
                try:
                    os.remove(temp_file)
                    temp_file = None
                except Exception as e:
                    print(f"Failed to remove original TTS file: {e}", file=sys.stderr)
        else:
            # Just play the original file at full volume
            play_cmd = f'aplay {temp_file}'
            if volume != 100:
                print("Volume control requires sox. Install with: sudo apt-get install sox")
        
        # Play the audio file
        play_result = subprocess.run(play_cmd, shell=True, capture_output=True, text=True)
        if play_result.returncode != 0:
            print(f"Audio playback error: {play_result.stderr}", file=sys.stderr)
            return 1
        
        return 0
    except Exception as e:
        print(f"TTS error: {e}", file=sys.stderr)
        return 1
    finally:
        # Always clean up the temp files
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
        if volume_file and os.path.exists(volume_file):
            try:
                os.remove(volume_file)
            except:
                pass


if __name__ == "__main__":
    sys.exit(main())