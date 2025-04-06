"use client";
import { useState, useRef, useCallback } from "react";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Mic2, Mic, Circle } from "lucide-react";
import { useWebSocket } from "@/contexts/WebSocketContext";

export default function PushToTalk() {
  const [isRecording, setIsRecording] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<string>("idle");
  const { status, sendAudioStream } = useWebSocket();
  
  const localStreamRef = useRef<MediaStream | null>(null);
  const recorderTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const isTransmittingRef = useRef(false);
  
  // Preferred MIME type – try OGG with opus first
  const mimeType = MediaRecorder.isTypeSupported('audio/ogg;codecs=opus')
    ? 'audio/ogg;codecs=opus'
    : MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : 'audio/webm';
  
  const startRecordingCycle = useCallback(async () => {
    try {
      if (!localStreamRef.current) {
        localStreamRef.current = await navigator.mediaDevices.getUserMedia({ audio: true });
      }
      const recorder = new MediaRecorder(localStreamRef.current, { mimeType });
      mediaRecorderRef.current = recorder;
      
      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          const reader = new FileReader();
          reader.onloadend = () => {
            const base64data = reader.result as string;
            sendAudioStream(base64data);
          };
          reader.readAsDataURL(event.data);
        }
      };
      
      recorder.onerror = (event) => {
        console.error("MediaRecorder error:", event.error);
        stopRecordingCycle();
      };
      
      recorder.onstart = () => {
        setIsRecording(true);
        setConnectionStatus("recording");
      };
      
      recorder.onstop = () => {
        setIsRecording(false);
        // If we're still transmitting, immediately restart the cycle
        if (isTransmittingRef.current) {
          startRecordingCycle();
        }
      };
      
      recorder.start();
      
      // Stop recorder after 2 seconds to force a complete file blob
      recorderTimeoutRef.current = setTimeout(() => {
        recorder.stop();
      }, 200);
    } catch (error) {
      console.error("Error in recording cycle:", error);
      setConnectionStatus("error");
    }
  }, [sendAudioStream, mimeType]);
  
  const stopRecordingCycle = useCallback(() => {
    isTransmittingRef.current = false;
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
    }
    if (recorderTimeoutRef.current) {
      clearTimeout(recorderTimeoutRef.current);
      recorderTimeoutRef.current = null;
    }
    if (localStreamRef.current) {
      localStreamRef.current.getTracks().forEach(track => track.stop());
      localStreamRef.current = null;
    }
    setIsRecording(false);
    setConnectionStatus("idle");
  }, []);
  
  const startTransmit = async () => {
    if (status !== "connected") return;
    isTransmittingRef.current = true;
    setConnectionStatus("connecting");
    await startRecordingCycle();
  };
  
  return (
    <Card className="p-4">
      <div className="flex flex-col gap-3">
        <div className="flex items-center space-x-2">
          <Mic2 className="h-5 w-5" />
          <h3 className="font-bold">Push To Talk (Periodic Recorder)</h3>
        </div>
        <div className="flex flex-col justify-center items-center space-y-2 min-h-[200px]">
          {connectionStatus !== "idle" && connectionStatus !== "recording" && (
            <div className="text-sm text-gray-500">
              {connectionStatus === "connecting" ? "Connecting..." : `Status: ${connectionStatus}`}
            </div>
          )}
          
          {!isRecording ? (
            <Button disabled={status !== "connected"} onClick={startTransmit}>
              <Mic className="h-4 w-4 mr-1" />
              Transmit
            </Button>
          ) : (
            <Button variant="destructive" onClick={stopRecordingCycle}>
              <Circle className="h-4 w-4 mr-1" />
              Mute
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}
