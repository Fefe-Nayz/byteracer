import asyncio
import logging
import json
import time
from typing import Optional, Dict, Any, Callable, List

import av
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate, MediaStreamTrack
from aiortc.contrib.media import MediaPlayer, MediaRecorder, MediaBlackhole
from aiortc.mediastreams import MediaStreamError, AudioStreamTrack

class AudioReceiveTrack(MediaStreamTrack):
    """
    A custom media track that receives audio from WebRTC
    and can be used for subsequent processing.
    """
    kind = "audio"

    def __init__(self, track, sound_manager=None):
        super().__init__()
        self.track = track
        self.sound_manager = sound_manager
        self._queue = asyncio.Queue()
        self._task = asyncio.create_task(self._run_track())
        self.sample_rate = 48000  # WebRTC standard sample rate
        self.is_muted = False

    async def _run_track(self):
        try:
            while True:
                frame = await self.track.recv()
                if not self.is_muted and self.sound_manager:
                    # Convert frame data for sound manager if needed
                    # Most sound managers will need PCM data (16-bit)
                    try:
                        await self._queue.put(frame)
                    except Exception as e:
                        logging.error(f"Error processing audio frame: {e}")
                else:
                    # If muted, still receive frames to keep the connection alive
                    # but don't process them
                    await self._queue.put(None)
        except MediaStreamError as e:
            logging.error(f"Media stream error: {e}")
        except asyncio.CancelledError:
            logging.info("Audio receive track task cancelled")
        except Exception as e:
            logging.error(f"Unexpected error in audio track: {e}")
        finally:
            self.stop()

    async def recv(self):
        """Get the next audio frame."""
        frame = await self._queue.get()
        return frame if frame else await self.track.recv()

    def stop(self):
        """Stop the audio track and clean up resources."""
        self.is_muted = True
        if self._task and not self._task.done():
            self._task.cancel()
        super().stop()

    def mute(self):
        """Mute the audio track."""
        self.is_muted = True

    def unmute(self):
        """Unmute the audio track."""
        self.is_muted = False

class WebRTCManager:
    """
    Manages WebRTC connections for audio communication with the robot.
    Uses WebSocket for signaling and aiortc for WebRTC.
    """
    
    def __init__(self, sound_manager=None):
        """
        Initialize the WebRTC manager.
        
        Args:
            sound_manager: Reference to the sound manager for audio playback
        """
        self.sound_manager = sound_manager
        self.peer_connection = None
        self.audio_track = None
        self.recorder = None
        self.ice_servers = [
            {"urls": "stun:stun.l.google.com:19302"},
            {"urls": "stun:stun1.l.google.com:19302"},
            {"urls": "stun:stun2.l.google.com:19302"},
            {"urls": "stun:stun3.l.google.com:19302"},
            {"urls": "stun:stun4.l.google.com:19302"},
        ]
        self.connection_state = "new"
        logging.info("WebRTC manager initialized")
    
    async def start(self):
        """
        Start the WebRTC manager.
        """
        logging.info("Starting WebRTC manager")
        # Nothing to do initially as connections are created on demand
    
    async def stop(self):
        """
        Stop the WebRTC manager and close any active connections.
        """
        logging.info("Stopping WebRTC manager")
        await self.close_connection()
    
    async def handle_offer(self, offer_data: dict):
        """
        Handle an incoming WebRTC offer.
        
        Args:
            offer_data: SDP offer data from the client
        """
        # Close any existing connection first
        await self.close_connection()
        
        # Create a new peer connection
        self.peer_connection = RTCPeerConnection(configuration={"iceServers": self.ice_servers})
        
        # Set up event handlers
        @self.peer_connection.on("connectionstatechange")
        async def on_connectionstatechange():
            logging.info(f"Connection state changed to: {self.peer_connection.connectionState}")
            self.connection_state = self.peer_connection.connectionState
            
            if self.peer_connection.connectionState == "failed":
                logging.error("WebRTC connection failed")
                await self.close_connection()
            
            elif self.peer_connection.connectionState == "disconnected":
                logging.info("WebRTC connection disconnected")
                await self.close_connection()
        
        @self.peer_connection.on("track")
        async def on_track(track):
            logging.info(f"Received {track.kind} track from client")
            
            if track.kind == "audio":
                self.audio_track = AudioReceiveTrack(track, self.sound_manager)
                
                # Set up audio playing/processing
                if self.sound_manager:
                    # Play incoming audio through the sound manager
                    try:
                        # Option 1: If sound manager supports direct track playback
                        if hasattr(self.sound_manager, 'play_webrtc_track'):
                            self.sound_manager.play_webrtc_track(self.audio_track)
                        
                        # Option 2: Save to file temporarily and play
                        # self.recorder = MediaRecorder('incoming_voice.wav')
                        # self.recorder.addTrack(self.audio_track)
                        # await self.recorder.start()
                        
                        logging.info("WebRTC audio track connected to sound manager")
                    except Exception as e:
                        logging.error(f"Error setting up audio playback: {e}")
                else:
                    logging.warning("No sound manager available for WebRTC audio")
                    # Blackhole consumes the track without doing anything
                    self.recorder = MediaBlackhole()
                    self.recorder.addTrack(self.audio_track)
                    await self.recorder.start()
            
            @track.on("ended")
            async def on_ended():
                logging.info(f"Track {track.kind} ended")
                if track.kind == "audio" and self.audio_track:
                    self.audio_track.stop()
        
        # Create and set the remote description
        offer = RTCSessionDescription(sdp=offer_data["sdp"], type=offer_data["type"])
        await self.peer_connection.setRemoteDescription(offer)
        
        # Create an answer
        answer = await self.peer_connection.createAnswer()
        await self.peer_connection.setLocalDescription(answer)
        
        # Return the answer to be sent back through the signaling channel
        return {
            "sdp": self.peer_connection.localDescription.sdp,
            "type": self.peer_connection.localDescription.type
        }
    
    async def handle_answer(self, answer_data: dict):
        """
        Handle an incoming WebRTC answer.
        
        Args:
            answer_data: SDP answer data from the client
        """
        if self.peer_connection:
            answer = RTCSessionDescription(sdp=answer_data["sdp"], type=answer_data["type"])
            await self.peer_connection.setRemoteDescription(answer)
            logging.info("Set remote description from answer")
        else:
            logging.error("No active peer connection to handle answer")
    
    async def handle_ice_candidate(self, candidate_data: dict):
        """
        Handle an incoming ICE candidate.
        
        Args:
            candidate_data: ICE candidate data from the client
        """
        if self.peer_connection:
            candidate = RTCIceCandidate(
                component=candidate_data.get("component", 0),
                foundation=candidate_data.get("foundation", ""),
                ip=candidate_data.get("ip", ""),
                port=candidate_data.get("port", 0),
                priority=candidate_data.get("priority", 0),
                protocol=candidate_data.get("protocol", ""),
                type=candidate_data.get("type", ""),
                sdpMid=candidate_data.get("sdpMid", ""),
                sdpMLineIndex=candidate_data.get("sdpMLineIndex", 0)
            )
            await self.peer_connection.addIceCandidate(candidate)
        else:
            logging.error("No active peer connection to handle ICE candidate")
    
    async def close_connection(self):
        """
        Close the current WebRTC connection and clean up resources.
        """
        logging.info("Closing WebRTC connection")
        
        # Stop audio track if active
        if self.audio_track:
            self.audio_track.stop()
            self.audio_track = None
        
        # Stop recorder if active
        if self.recorder:
            await self.recorder.stop()
            self.recorder = None
        
        # Close peer connection
        if self.peer_connection:
            await self.peer_connection.close()
            self.peer_connection = None
        
        self.connection_state = "closed"
        logging.info("WebRTC connection closed")