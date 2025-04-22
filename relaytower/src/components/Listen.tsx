"use client";
import { useState, useRef, useEffect, useCallback } from "react";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Volume2, VolumeX, Headphones } from "lucide-react";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { Switch } from "./ui/switch";
import { Label } from "./ui/label";
import { useGamepadContext } from "@/contexts/GamepadContext";
import { useLocalStorage } from "@/hooks/useLocalStorage";

// Extend Window interface to include webkitAudioContext
interface WindowWithAudioContext extends Window {
  webkitAudioContext?: typeof AudioContext;
}

export default function Listen() {
  const [isListening, setIsListening] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<string>("idle");
  const [toggleMode, setToggleMode] = useLocalStorage<boolean>("listen-toggleMode", false);
  const [audioEnabled, setAudioEnabled] = useState(true);
    // Access WebSocket context
  const { status, startListening: wsStartListening, stopListening: wsStopListening } = useWebSocket();
  
  // Access gamepad context for button functionality
  const { isActionActive } = useGamepadContext();
  
  // Track the previous state of the listen button
  const prevListenState = useRef<boolean>(false);
  
  // Audio context and nodes
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioSourceRef = useRef<AudioBufferSourceNode | null>(null);
  const gainNodeRef = useRef<GainNode | null>(null);
  
  // Clean up audio resources
  const cleanupAudio = useCallback(() => {
    if (audioSourceRef.current) {
      try {
        audioSourceRef.current.stop();
      } catch (e) {
        console.error("Error stopping audio source:", e);
      }
      audioSourceRef.current = null;
    }
    
    setIsListening(false);
    setIsConnecting(false);
    setConnectionStatus("idle");
  }, []);
    // Start listening for audio from robot
  const startListening = useCallback(() => {
    try {
      setIsConnecting(true);
      setConnectionStatus("connecting");
        // Create AudioContext if it doesn't exist
      if (!audioContextRef.current) {
        audioContextRef.current = new (window.AudioContext || (window as WindowWithAudioContext).webkitAudioContext)();
      }
      
      // Initialize gain node if it doesn't exist
      if (!gainNodeRef.current && audioContextRef.current) {
        gainNodeRef.current = audioContextRef.current.createGain();
        gainNodeRef.current.connect(audioContextRef.current.destination);
      }
      
      // Send command to robot to start streaming audio
      wsStartListening();
      
      // Update UI state
      setIsListening(true);
      setConnectionStatus("listening");
      setIsConnecting(false);
      
      console.log("Started listening to robot microphone");
    } catch (error) {
      console.error("Error starting audio listening:", error);
      setConnectionStatus("error");
      setIsConnecting(false);
    }
  }, [wsStartListening]);
    // Stop listening
  const stopListening = () => {
    // Tell the robot to stop streaming audio
    wsStopListening();
    
    // Clean up local audio resources
    cleanupAudio();
    console.log("Stopped listening to robot microphone");
  };
  
  // Listen for audio data from WebSocket
  useEffect(() => {
    const handleAudioData = (event: CustomEvent) => {
      if (!isListening || !audioEnabled) return;
      
      try {
        // Process incoming audio data
        const audioData = event.detail.audioData;
        if (!audioData || !audioContextRef.current || !gainNodeRef.current) return;
        
        // Convert base64 audio data to ArrayBuffer
        const base64Data = audioData.split(',')[1];
        const binaryString = window.atob(base64Data);
        const bytes = new Uint8Array(binaryString.length);
        
        for (let i = 0; i < binaryString.length; i++) {
          bytes[i] = binaryString.charCodeAt(i);
        }
        
        const audioBuffer = bytes.buffer;
        
        // Decode the audio data
        audioContextRef.current.decodeAudioData(audioBuffer, (buffer) => {
          // Create a new source for this chunk
          const source = audioContextRef.current!.createBufferSource();
          source.buffer = buffer;
          source.connect(gainNodeRef.current!);
          
          // Store the source in ref for potential cleanup
          audioSourceRef.current = source;
          
          // Play the audio chunk
          source.start(0);
          
          // After audio ends, clear the source reference
          source.onended = () => {
            audioSourceRef.current = null;
          };
        }, (error) => {
          console.error("Error decoding audio data:", error);
        });
      } catch (error) {
        console.error("Error processing audio data:", error);
      }
    };
    
    // Register event listener for robot audio data
    window.addEventListener(
      "robot:audio-data",
      handleAudioData as EventListener
    );
    
    return () => {
      window.removeEventListener(
        "robot:audio-data",
        handleAudioData as EventListener
      );
    };
  }, [isListening, audioEnabled]);
  
  // Auto-mute when PushToTalk is active to prevent echo
  useEffect(() => {
    const handlePushToTalkStatus = (event: CustomEvent) => {
      const isPushToTalkActive = event.detail.isActive;
      
      if (isPushToTalkActive && isListening) {
        // Temporarily disable audio when push-to-talk is active
        setAudioEnabled(false);
        console.log("Audio listening muted due to push-to-talk activity");
      } else {
        // Re-enable audio when push-to-talk is no longer active
        setAudioEnabled(true);
        console.log("Audio listening restored after push-to-talk");
      }
    };
    
    window.addEventListener(
      "pushToTalk:status",
      handlePushToTalkStatus as EventListener
    );
    
    return () => {
      window.removeEventListener(
        "pushToTalk:status",
        handlePushToTalkStatus as EventListener
      );
    };
  }, [isListening]);
  
  // Toggle listening based on gamepad button
  useEffect(() => {
    if (status !== "connected") return;
  
    const listenButtonActive = isActionActive("listen");
    
    if (listenButtonActive === prevListenState.current) {
      return;
    }
    
    console.log(`Listen button active: ${listenButtonActive}, Previous state: ${prevListenState.current}`);
    
    if (toggleMode) {
      // Toggle on a rising edge (button press)
      if (listenButtonActive && !prevListenState.current) {
        if (isListening) {
          stopListening();
          console.log("Stopped listening (toggle mode).");
        } else {
          startListening();
          console.log("Started listening (toggle mode).");
        }
      }
    } else {
      // HOLD MODE: start on press, stop on release
      if (listenButtonActive && !isListening) {
        startListening();
        console.log("Started listening (hold mode).");
      } else if (!listenButtonActive && isListening) {
        stopListening();
        console.log("Stopped listening (hold mode).");
      }
    }
    
    prevListenState.current = listenButtonActive;
  }, [
    status,
    isActionActive,
    isListening,
    toggleMode,
    startListening,
    stopListening
  ]);
  
  // Cleanup on unmount
  useEffect(() => {
    return () => {
      cleanupAudio();
      
      // Close AudioContext
      if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
        audioContextRef.current.close();
      }
    };
  }, [cleanupAudio]);
  
  return (
    <Card className="p-4">
      <div className="flex flex-col justify-between gap-3">
        <div className="flex items-center space-x-2">
          <Headphones className="h-5 w-5" />
          <h3 className="font-bold">Listen to Robot</h3>
        </div>
        
        <div className="flex items-center space-x-2 mt-2">
          <Switch 
            id="toggle-mode-listen" 
            checked={toggleMode} 
            onCheckedChange={setToggleMode} 
          />
          <Label htmlFor="toggle-mode-listen">
            {toggleMode ? "Toggle mode (press once)" : "Hold to listen mode"}
          </Label>
        </div>
        
        <div className="flex flex-col justify-center items-center space-y-2 min-h-[200px]">
          {connectionStatus !== "idle" && connectionStatus !== "listening" && (
            <div className="text-sm text-gray-500 mb-2">
              {connectionStatus === "connecting" ? "Establishing connection..." : `Status: ${connectionStatus}`}
            </div>
          )}

          {!isListening ? (
            <Button 
              disabled={status !== "connected" || isConnecting}
              onClick={startListening}
            >
              <Volume2 className="h-4 w-4 mr-1" />
              {isConnecting ? "Connecting..." : "Start Listening"}
            </Button>
          ) : (
            <Button variant="destructive" onClick={stopListening}>
              <VolumeX className="h-4 w-4 mr-1" />
              Stop Listening
            </Button>
          )}

          {connectionStatus === "error" && (
            <div className="text-sm text-red-500 mt-2">
              Connection error. Please try again.
            </div>
          )}
          
          <div className="text-sm text-gray-500 mt-3">
            <p>Press the gamepad button mapped to &quot;Listen&quot; to {toggleMode ? "toggle listening on/off" : "listen while holding"}.</p>
          </div>
        </div>
      </div>
    </Card>
  );
}
