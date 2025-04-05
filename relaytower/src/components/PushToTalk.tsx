import { useState, useRef, useEffect } from "react";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Mic2, Mic, Circle } from "lucide-react";
import { useWebSocket } from "@/contexts/WebSocketContext";

export default function PushToTalk() {
  const [isTalking, setIsTalking] = useState(false);
  const [isReady, setIsReady] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const { status, sendAudioStream } = useWebSocket();
  
  // Audio context refs
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioWorkletNodeRef = useRef<AudioWorkletNode | null>(null);
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  // Initialize AudioWorklet when component mounts
  useEffect(() => {
    let mounted = true;
    
    const initAudioWorklet = async () => {
      try {
        // Create AudioContext
        const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
        audioContextRef.current = ctx;
        
        // Load and register the audio processor
        await ctx.audioWorklet.addModule('/audio-processor.js');
        console.log('Audio worklet module loaded successfully');
        
        if (mounted) {
          setIsReady(true);
          setErrorMessage(null);
        }
      } catch (err) {
        console.error('Failed to initialize audio worklet:', err);
        if (mounted) {
          setIsReady(false);
          setErrorMessage('Failed to initialize audio processor. Please refresh the page.');
        }
      }
    };
    
    initAudioWorklet();
    
    return () => {
      mounted = false;
      
      // Clean up
      if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
        audioContextRef.current.close();
      }
    };
  }, []);

  const startTalk = async () => {
    if (!isReady || status !== "connected") {
      console.error("Not ready or WebSocket not connected");
      return;
    }

    try {
      const ctx = audioContextRef.current;
      if (!ctx) {
        console.error("AudioContext not initialized");
        return;
      }
      
      // Resume audio context (needed for some browsers)
      if (ctx.state !== 'running') {
        await ctx.resume();
      }
      
      // Get microphone stream
      console.log("Requesting microphone access...");
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: true, 
        video: false 
      });
      streamRef.current = stream;
      console.log("Microphone access granted");
      
      // Create source node
      const source = ctx.createMediaStreamSource(stream);
      sourceNodeRef.current = source;
      
      // Create AudioWorkletNode with the simple processor
      const workletNode = new AudioWorkletNode(ctx, 'simple-audio-processor');
      audioWorkletNodeRef.current = workletNode;
      
      // Connect nodes
      source.connect(workletNode);
      
      // Listen for messages from the processor
      workletNode.port.onmessage = (event) => {
        const audioBuffer = event.data.buffer;
        const sampleRate = event.data.sampleRate;
        
        // Convert to Int16Array for transmission
        const audioArray = convertFloat32ToInt16(audioBuffer);
        
        console.log(`Sending ${audioArray.length} samples`);
        
        // Send the audio packet
        sendAudioStream(audioArray, sampleRate);
      };
      
      setIsTalking(true);
      console.log("Push to Talk activated - simple mode");
    } catch (error) {
      console.error("Error starting audio capture:", error);
      setErrorMessage(error instanceof Error ? error.message : "Unknown error");
      setIsTalking(false);
    }
  };

  const stopTalk = () => {
    setIsTalking(false);
    console.log("Push to Talk deactivated");

    // Stop the stream tracks
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }

    // Disconnect audio nodes
    if (sourceNodeRef.current && audioWorkletNodeRef.current) {
      sourceNodeRef.current.disconnect(audioWorkletNodeRef.current);
      sourceNodeRef.current = null;
    }

    if (audioWorkletNodeRef.current) {
      audioWorkletNodeRef.current.disconnect();
      audioWorkletNodeRef.current = null;
    }
  };

  // Helper function to convert Float32Array to Int16Array
  const convertFloat32ToInt16 = (buffer: Float32Array): number[] => {
    const output = new Int16Array(buffer.length);
    
    for (let i = 0; i < buffer.length; i++) {
      // Simple linear conversion from float to int16
      const s = Math.max(-1, Math.min(1, buffer[i]));
      output[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    
    return Array.from(output);
  };

  return (
    <Card className="p-4">
      <div className="flex flex-col justify-between gap-3">
        <div className="flex items-center space-x-2">
          <Mic2 className="h-5 w-5" />
          <h3 className="font-bold">Push To Talk (Simple)</h3>
        </div>

        <div className="flex flex-col justify-center items-center space-y-2 min-h-[200px]">
          {errorMessage && (
            <p className="text-red-500 text-sm mb-2">{errorMessage}</p>
          )}
          
          {!isTalking ? (
            <Button 
              disabled={!isReady || status !== "connected"} 
              onClick={startTalk}
            >
              <Mic className="h-4 w-4 mr-1" />
              Transmit
            </Button>
          ) : (
            <Button variant="destructive" onClick={stopTalk}>
              <Circle className="h-4 w-4 mr-1" />
              Mute
            </Button>
          )}
          
          {!isReady && !errorMessage && (
            <p className="text-sm text-gray-500 mt-2">Initializing audio system...</p>
          )}
        </div>
      </div>
    </Card>
  );
}