import { useState, useRef, useEffect, useCallback } from "react";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Mic2, Mic, Circle } from "lucide-react";
import { useWebSocket } from "@/contexts/WebSocketContext";

// Define default ICE servers (STUN/TURN servers for NAT traversal)
const DEFAULT_ICE_SERVERS = [
  { urls: 'stun:stun.l.google.com:19302' },
  { urls: 'stun:stun1.l.google.com:19302' },
  { urls: 'stun:stun2.l.google.com:19302' },
  { urls: 'stun:stun3.l.google.com:19302' },
  { urls: 'stun:stun4.l.google.com:19302' },
];

export default function PushToTalk() {
  const [isTalking, setIsTalking] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<string>("idle");
  const { status, sendWebRTCOffer, sendWebRTCAnswer, sendWebRTCIceCandidate, sendWebRTCDisconnect } = useWebSocket();
  
  // Refs for WebRTC objects
  const peerConnectionRef = useRef<RTCPeerConnection | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);

  // Initialize WebRTC listeners
  useEffect(() => {
    // Set up event listeners for WebRTC signaling
    const handleOffer = (event: CustomEvent<RTCSessionDescriptionInit>) => {
      console.log("Received WebRTC offer");
      handleIncomingOffer(event.detail);
    };

    const handleAnswer = (event: CustomEvent<RTCSessionDescriptionInit>) => {
      console.log("Received WebRTC answer");
      if (peerConnectionRef.current) {
        peerConnectionRef.current.setRemoteDescription(event.detail)
          .catch(err => {
            console.error("Error setting remote description from answer:", err);
            setConnectionStatus("error");
          });
      }
    };

    const handleIceCandidate = (event: CustomEvent<RTCIceCandidate>) => {
      console.log("Received ICE candidate");
      if (peerConnectionRef.current) {
        peerConnectionRef.current.addIceCandidate(event.detail)
          .catch(err => {
            console.error("Error adding received ICE candidate:", err);
          });
      }
    };

    const handleDisconnect = () => {
      console.log("Received WebRTC disconnect request");
      cleanupWebRTC();
    };

    // Add event listeners
    window.addEventListener("webrtc:offer", handleOffer as EventListener);
    window.addEventListener("webrtc:answer", handleAnswer as EventListener);
    window.addEventListener("webrtc:ice-candidate", handleIceCandidate as EventListener);
    window.addEventListener("webrtc:disconnect", handleDisconnect);

    return () => {
      // Clean up event listeners
      window.removeEventListener("webrtc:offer", handleOffer as EventListener);
      window.removeEventListener("webrtc:answer", handleAnswer as EventListener);
      window.removeEventListener("webrtc:ice-candidate", handleIceCandidate as EventListener);
      window.removeEventListener("webrtc:disconnect", handleDisconnect);
      
      // Clean up WebRTC connection
      cleanupWebRTC();
    };
  }, []);

  // Clean up WebRTC resources
  const cleanupWebRTC = useCallback(() => {
    // Stop media recorder if running
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    
    // Stop all tracks in local stream
    if (localStreamRef.current) {
      localStreamRef.current.getTracks().forEach(track => {
        track.stop();
      });
      localStreamRef.current = null;
    }
    
    // Close peer connection
    if (peerConnectionRef.current) {
      peerConnectionRef.current.close();
      peerConnectionRef.current = null;
    }
    
    // Reset state
    setIsTalking(false);
    setIsConnecting(false);
    setConnectionStatus("idle");
  }, []);

  // Handle an incoming WebRTC offer
  const handleIncomingOffer = async (offer: RTCSessionDescriptionInit) => {
    try {
      // Create new peer connection
      const pc = createPeerConnection();
      if (!pc) return;
      
      // Set the remote description from the offer
      await pc.setRemoteDescription(offer);
      
      // Create answer to the offer
      const answer = await pc.createAnswer();
      await pc.setLocalDescription(answer);
      
      // Send the answer to the robot through the signaling channel
      sendWebRTCAnswer(answer);
      
      setConnectionStatus("connected");
    } catch (error) {
      console.error("Error handling incoming offer:", error);
      setConnectionStatus("error");
    }
  };

  // Create a WebRTC peer connection
  const createPeerConnection = () => {
    try {
      const pc = new RTCPeerConnection({
        iceServers: DEFAULT_ICE_SERVERS
      });
      
      // Set up event handlers
      pc.onicecandidate = handleICECandidate;
      pc.oniceconnectionstatechange = () => {
        console.log("ICE connection state:", pc.iceConnectionState);
        if (pc.iceConnectionState === 'connected' || pc.iceConnectionState === 'completed') {
          setConnectionStatus("connected");
          setIsConnecting(false);
        } else if (pc.iceConnectionState === 'failed' || pc.iceConnectionState === 'disconnected' || pc.iceConnectionState === 'closed') {
          setConnectionStatus(pc.iceConnectionState);
          setIsConnecting(false);
          setIsTalking(false);
        }
      };
      
      pc.onconnectionstatechange = () => {
        console.log("Connection state:", pc.connectionState);
        if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected' || pc.connectionState === 'closed') {
          cleanupWebRTC();
        }
      };
      
      peerConnectionRef.current = pc;
      return pc;
    } catch (error) {
      console.error("Error creating peer connection:", error);
      setConnectionStatus("error");
      return null;
    }
  };

  // Handle ICE candidate events
  const handleICECandidate = (event: RTCPeerConnectionIceEvent) => {
    if (event.candidate) {
      console.log("Generated ICE candidate");
      // Send the ICE candidate to the other peer
      sendWebRTCIceCandidate(event.candidate);
    }
  };

  // Start the WebRTC connection and begin talking
  const startTalk = async () => {
    try {
      setIsConnecting(true);
      setConnectionStatus("connecting");
      
      // Get audio stream from microphone
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      localStreamRef.current = stream;
      
      // Create peer connection
      const pc = createPeerConnection();
      if (!pc) {
        throw new Error("Failed to create peer connection");
      }
      
      // Add audio tracks to the peer connection
      stream.getAudioTracks().forEach(track => {
        if (pc && localStreamRef.current) {
          pc.addTrack(track, localStreamRef.current);
        }
      });
      
      // Create and send offer
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      
      // Send the offer via signaling channel
      sendWebRTCOffer(offer);
      
      setIsTalking(true);
    } catch (error) {
      console.error("Error starting WebRTC connection:", error);
      setConnectionStatus("error");
      setIsConnecting(false);
      
      // Clean up any partial setup
      if (localStreamRef.current) {
        localStreamRef.current.getTracks().forEach(track => track.stop());
        localStreamRef.current = null;
      }
    }
  };

  // Stop talking and clean up WebRTC connection
  const stopTalk = () => {
    // Send disconnect message to the other peer
    sendWebRTCDisconnect();
    
    // Clean up local resources
    cleanupWebRTC();
  };

  return (
    <Card className="p-4">
      <div className="flex flex-col justify-between gap-3">
        <div className="flex items-center space-x-2">
          <Mic2 className="h-5 w-5" />
          <h3 className="font-bold">Push To Talk (WebRTC)</h3>
        </div>

        <div className="flex flex-col justify-center items-center space-y-2 min-h-[200px]">
          {connectionStatus !== "idle" && connectionStatus !== "connected" && (
            <div className="text-sm text-gray-500 mb-2">
              {connectionStatus === "connecting" ? "Establishing connection..." : `Status: ${connectionStatus}`}
            </div>
          )}
          
          {!isTalking ? (
            <Button 
              disabled={status !== "connected" || isConnecting} 
              onClick={startTalk}
            >
              <Mic className="h-4 w-4 mr-1" />
              {isConnecting ? "Connecting..." : "Transmit"}
            </Button>
          ) : (
            <Button variant="destructive" onClick={stopTalk}>
              <Circle className="h-4 w-4 mr-1" />
              Mute
            </Button>
          )}
          
          {connectionStatus === "error" && (
            <div className="text-sm text-red-500 mt-2">
              Connection error. Please try again.
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}