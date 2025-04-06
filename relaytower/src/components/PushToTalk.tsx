"use client";
import { useState, useRef, useCallback } from "react";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Mic2, Mic, Circle } from "lucide-react";
import { useWebSocket } from "@/contexts/WebSocketContext";

export default function PushToTalk() {
  const [isRecording, setIsRecording] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<string>("idle");
  
  // Access WebSocket context – now we can send audio chunks via sendAudioStream
  const { status, sendAudioStream } = useWebSocket();
  
  // Refs to hold the MediaRecorder and MediaStream
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);

  // Clean-up function to stop recording and release audio resources
  const cleanupRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    if (localStreamRef.current) {
      localStreamRef.current.getTracks().forEach(track => track.stop());
      localStreamRef.current = null;
    }
    setIsRecording(false);
    setIsConnecting(false);
    setConnectionStatus("idle");
  }, []);

  // Start recording and sending audio chunks
  const startRecording = async () => {
    try {
      setIsConnecting(true);
      setConnectionStatus("connecting");
      
      // Get audio stream from the microphone
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      localStreamRef.current = stream;
      
      // Create a MediaRecorder – adjust the MIME type as needed (audio/webm is common)
      const options = { mimeType: 'audio/webm' };
      const mediaRecorder = new MediaRecorder(stream, options);
      mediaRecorderRef.current = mediaRecorder;
      
      mediaRecorder.onstart = () => {
        console.log("MediaRecorder started");
        setIsRecording(true);
        setConnectionStatus("recording");
      };
      
      // When data is available, convert the Blob to a Base64 data URL and send it via WebSocket
      mediaRecorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          const reader = new FileReader();
          reader.onloadend = () => {
            const base64data = reader.result as string;
            sendAudioStream(base64data);
          };
          reader.readAsDataURL(event.data);
        }
      };
      
      mediaRecorder.onerror = (event) => {
        console.error("MediaRecorder error:", event.error);
        cleanupRecording();
      };
      
      // Start recording and request a chunk every 250ms (tweak the interval as needed)
      mediaRecorder.start(250);
      setIsConnecting(false);
    } catch (error) {
      console.error("Error starting audio recording:", error);
      setConnectionStatus("error");
      setIsConnecting(false);
    }
  };

  // Stop recording and clean up resources
  const stopRecording = () => {
    cleanupRecording();
  };

  return (
    <Card className="p-4">
      <div className="flex flex-col justify-between gap-3">
        <div className="flex items-center space-x-2">
          <Mic2 className="h-5 w-5" />
          <h3 className="font-bold">Push To Talk (MediaRecorder)</h3>
        </div>
        <div className="flex flex-col justify-center items-center space-y-2 min-h-[200px]">
          {connectionStatus !== "idle" && connectionStatus !== "recording" && (
            <div className="text-sm text-gray-500 mb-2">
              {connectionStatus === "connecting" ? "Establishing connection..." : `Status: ${connectionStatus}`}
            </div>
          )}
          
          {!isRecording ? (
            <Button 
              disabled={status !== "connected" || isConnecting} 
              onClick={startRecording}
            >
              <Mic className="h-4 w-4 mr-1" />
              {isConnecting ? "Connecting..." : "Transmit"}
            </Button>
          ) : (
            <Button variant="destructive" onClick={stopRecording}>
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
