import { useState, useRef } from "react";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Mic2, Mic, Circle } from "lucide-react";
import { useWebSocket } from "@/contexts/WebSocketContext";

// Configuration for audio processing
const BUFFER_SIZE = 4096;
const SAMPLE_RATE = 44100;
const TARGET_SAMPLE_RATE = 16000;

// Extend Window interface to include webkitAudioContext
declare global {
  interface Window {
    webkitAudioContext: typeof AudioContext;
  }
}

export default function PushToTalk() {
  const [isTalking, setIsTalking] = useState(false);
  const { status, sendAudioStream } = useWebSocket();
  
  // Audio context refs
  const audioContextRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const inputRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const startTalk = async () => {
    if (status !== "connected") {
      console.error("WebSocket not connected");
      return;
    }

    try {
      setIsTalking(true);
      console.log("Push to Talk activated");

      // Initialize audio context with proper typing
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      audioContextRef.current = new AudioContextClass({
        latencyHint: 'interactive',
      });

      // Create processor
      const processor = audioContextRef.current.createScriptProcessor(BUFFER_SIZE, 1, 1);
      processorRef.current = processor;
      processor.connect(audioContextRef.current.destination);

      // Get microphone stream
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      streamRef.current = stream;
      
      // Create audio source from stream
      const input = audioContextRef.current.createMediaStreamSource(stream);
      inputRef.current = input;
      input.connect(processor);

      // Process audio data
      processor.onaudioprocess = (e) => {
        if (status === "connected" && isTalking) {
          const left = e.inputBuffer.getChannelData(0);
          const downsampled = downsampleBuffer(left, SAMPLE_RATE, TARGET_SAMPLE_RATE);
          
          // Convert the audio data to Int16Array and then to an array of numbers for WebSocket transmission
          const audioArray = Array.from(new Int16Array(downsampled));
          
          // Use the specialized function to send audio data
          sendAudioStream(audioArray, TARGET_SAMPLE_RATE);
        }
      };

      // Resume audio context
      await audioContextRef.current.resume();

    } catch (error) {
      console.error("Error starting audio capture:", error);
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
    if (inputRef.current && processorRef.current) {
      inputRef.current.disconnect(processorRef.current);
      inputRef.current = null;
    }

    if (processorRef.current && audioContextRef.current) {
      processorRef.current.disconnect(audioContextRef.current.destination);
      processorRef.current = null;
    }

    // Close audio context
    if (audioContextRef.current) {
      audioContextRef.current.close().then(() => {
        audioContextRef.current = null;
      });
    }
  };

  // Function to downsample audio buffer
  const downsampleBuffer = (buffer: Float32Array, sampleRate: number, outSampleRate: number) => {
    if (outSampleRate === sampleRate) {
      return buffer.buffer;
    }
    
    if (outSampleRate > sampleRate) {
      throw new Error('Downsampling rate should be smaller than original sample rate');
    }
    
    const sampleRateRatio = sampleRate / outSampleRate;
    const newLength = Math.round(buffer.length / sampleRateRatio);
    const result = new Int16Array(newLength);
    let offsetResult = 0;
    let offsetBuffer = 0;
    
    while (offsetResult < result.length) {
      const nextOffsetBuffer = Math.round((offsetResult + 1) * sampleRateRatio);
      let accum = 0;
      let count = 0;
      
      for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
        accum += buffer[i];
        count++;
      }
      
      result[offsetResult] = Math.min(1, accum / count) * 0x7FFF;
      offsetResult++;
      offsetBuffer = nextOffsetBuffer;
    }
    
    return result.buffer;
  };

  return (
    <Card className="p-4">
      <div className="flex flex-col justify-between gap-3">
        <div className="flex items-center space-x-2">
          <Mic2 className="h-5 w-5" />
          <h3 className="font-bold">Push To Talk</h3>
        </div>

        <div className="flex justify-center items-center space-x-2 min-h-[200px]">
          {!isTalking ? (
            <Button 
              disabled={status !== "connected"} 
              onClick={startTalk}
            >
              <Mic className="h-4 w-4 mr-1" />
              Transmit
            </Button>) : (<Button variant="destructive" onClick={stopTalk}>
              <Circle className="h-4 w-4 mr-1" />
              Mute
            </Button>)}
        </div>
      </div>
    </Card>
  );
}