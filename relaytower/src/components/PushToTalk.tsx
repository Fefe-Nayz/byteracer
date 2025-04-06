"use client";
import { useState, useRef, useEffect, useCallback } from "react";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Mic2, Mic, Circle } from "lucide-react";
import { useWebSocket } from "@/contexts/WebSocketContext";

// Import the extendable MediaRecorder and the WAV encoder
import { MediaRecorder as ExtendableMediaRecorder, register } from "extendable-media-recorder";
import { connect } from "extendable-media-recorder-wav-encoder";

export default function PushToTalk() {
  const [isRecording, setIsRecording] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<string>("idle");

  // Access your WebSocket context – we'll call sendAudioStream() with each chunk
  const { status, sendAudioStream } = useWebSocket();

  // Refs to hold the MediaRecorder and MediaStream
  type ExtendableMediaRecorderInstance = InstanceType<typeof ExtendableMediaRecorder>;

  const mediaRecorderRef = useRef<ExtendableMediaRecorderInstance | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const wavHeaderRef = useRef<ArrayBuffer | null>(null);

  // We only need to register the WAV encoder once. We'll do this in a useEffect.
  const [encoderReady, setEncoderReady] = useState(false);

  useEffect(() => {
    // Async IIFE so we can await the encoder registration
    (async () => {
      try {
        // Register the WAV encoder
        await register(await connect());
        console.log("WAV encoder registered successfully.");
        setEncoderReady(true);
      } catch (err) {
        console.error("Error registering WAV encoder:", err);
      }
    })();
  }, []);

  // Clean-up function: stop recording, release audio resources
  const cleanupRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
    }
    if (localStreamRef.current) {
      localStreamRef.current.getTracks().forEach((track) => track.stop());
      localStreamRef.current = null;
    }
    wavHeaderRef.current = null;
    setIsRecording(false);
    setIsConnecting(false);
    setConnectionStatus("idle");
  }, []);

  // Extract WAV header from the first chunk
  const extractWavHeader = (arrayBuffer: ArrayBuffer): ArrayBuffer => {
    // Standard WAV header is 44 bytes
    // But to be safe, we'll use a heuristic to find the data section
    // by looking for the "data" chunk marker
    const view = new DataView(arrayBuffer);
    
    // First, verify this looks like a WAV file
    const riff = String.fromCharCode(view.getUint8(0), view.getUint8(1), view.getUint8(2), view.getUint8(3));
    if (riff !== "RIFF") {
      console.error("Not a valid WAV file (no RIFF header)");
      return arrayBuffer.slice(0, 44); // Just use first 44 bytes as fallback
    }
    
    // Look for the "data" chunk marker which comes immediately before actual audio data
    // "data" in ASCII is 100, 97, 116, 97
    for (let i = 12; i < Math.min(arrayBuffer.byteLength - 4, 1024); i++) {
      if (view.getUint8(i) === 100 && 
          view.getUint8(i+1) === 97 && 
          view.getUint8(i+2) === 116 && 
          view.getUint8(i+3) === 97) {
        // Found the data chunk - the header extends 8 bytes past this marker
        // (4 bytes for "data" and 4 bytes for the data chunk size)
        return arrayBuffer.slice(0, i + 8);
      }
    }
    
    // If we couldn't find the data marker, use a default 44-byte header
    console.warn("Could not find data chunk in WAV - using standard 44-byte header");
    return arrayBuffer.slice(0, 44);
  };

  // Create a complete WAV file by prepending the header to data
  const createWavWithHeader = async (
    data: Blob, 
    header: ArrayBuffer | null
  ): Promise<string> => {
    return new Promise((resolve, reject) => {
      // If we don't have a header yet, or this is already a complete WAV file, just return the data
      if (!header) {
        const reader = new FileReader();
        reader.onloadend = () => resolve(reader.result as string);
        reader.onerror = reject;
        reader.readAsDataURL(data);
        return;
      }

      // Convert the Blob to ArrayBuffer to get the raw audio data
      const blobReader = new FileReader();
      blobReader.onload = () => {
        try {
          const dataBuffer = blobReader.result as ArrayBuffer;
          
          // Check if this is already a complete WAV with RIFF header
          const hasHeader = new DataView(dataBuffer).getUint32(0, false) === 0x52494646; // "RIFF" in hex
          
          if (hasHeader) {
            // Data already has a header, no need to modify
            const reader = new FileReader();
            reader.onloadend = () => resolve(reader.result as string);
            reader.onerror = reject;
            reader.readAsDataURL(data);
            return;
          }
          
          // Create a new ArrayBuffer with the header + data
          const result = new ArrayBuffer(header.byteLength + dataBuffer.byteLength);
          const resultView = new Uint8Array(result);
          
          // Copy the header
          resultView.set(new Uint8Array(header), 0);
          
          // Copy the data right after the header
          resultView.set(new Uint8Array(dataBuffer), header.byteLength);
          
          // Update the size fields in the WAV header
          const view = new DataView(result);
          
          // Update the file size (subtract 8 from total size)
          view.setUint32(4, result.byteLength - 8, true);
          
          // Find the data chunk size field - it's after the "data" marker
          // which we found earlier in extractWavHeader
          for (let i = 12; i < header.byteLength - 4; i++) {
            if (view.getUint8(i) === 100 && 
                view.getUint8(i+1) === 97 && 
                view.getUint8(i+2) === 116 && 
                view.getUint8(i+3) === 97) {
              // Update the data chunk size
              view.setUint32(i + 4, dataBuffer.byteLength, true);
              break;
            }
          }
          
          // Convert to base64
          const base64 = btoa(
            new Uint8Array(result)
              .reduce((data, byte) => data + String.fromCharCode(byte), '')
          );
          
          resolve(`data:audio/wav;base64,${base64}`);
        } catch (error) {
          console.error("Error processing audio chunk:", error);
          reject(error);
        }
      };
      blobReader.onerror = reject;
      blobReader.readAsArrayBuffer(data);
    });
  };

  // Start recording (as WAV) and send chunks via WebSocket
  const startRecording = async () => {
    try {
      if (!encoderReady) {
        console.warn("WAV encoder is not yet ready.");
        return;
      }
      setIsConnecting(true);
      setConnectionStatus("connecting");

      // Reset the WAV header
      wavHeaderRef.current = null;

      // Request microphone
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      localStreamRef.current = stream;

      // Use the extendable MediaRecorder with { mimeType: "audio/wav" }
      const options = { mimeType: "audio/wav" };
      const mediaRecorder = new ExtendableMediaRecorder(stream, options);
      mediaRecorderRef.current = mediaRecorder;

      mediaRecorder.onstart = () => {
        console.log("ExtendableMediaRecorder started (WAV).");
        setIsRecording(true);
        setConnectionStatus("recording");
      };

      // Send each chunk as Base64 with proper WAV headers
      mediaRecorder.ondataavailable = async (event) => {
        if (event.data && event.data.size > 0) {
          try {
            // Convert the blob to ArrayBuffer to extract header if needed
            const arrayBuffer = await event.data.arrayBuffer();
            
            // If this is the first chunk, extract and save the header
            if (wavHeaderRef.current === null) {
              wavHeaderRef.current = extractWavHeader(arrayBuffer);
              console.log(`Extracted WAV header: ${wavHeaderRef.current.byteLength} bytes`);
              
              // First chunk already has a complete header, send as is
              const reader = new FileReader();
              reader.onloadend = () => {
                const base64data = reader.result as string;
                sendAudioStream(base64data);
              };
              reader.readAsDataURL(event.data);
            } else {
              // For subsequent chunks, create a new WAV by prepending the saved header
              const completeWav = await createWavWithHeader(event.data, wavHeaderRef.current);
              sendAudioStream(completeWav);
            }
          } catch (error) {
            console.error("Error processing audio chunk:", error);
          }
        }
      };

      mediaRecorder.onerror = (event) => {
        console.error("ExtendableMediaRecorder error:", event.error);
        cleanupRecording();
      };

      // Start recording with ~200ms intervals
      mediaRecorder.start(200);
      setIsConnecting(false);
    } catch (error) {
      console.error("Error starting WAV recording:", error);
      setConnectionStatus("error");
      setIsConnecting(false);
    }
  };

  // Stop recording
  const stopRecording = () => {
    cleanupRecording();
  };

  return (
    <Card className="p-4">
      <div className="flex flex-col justify-between gap-3">
        <div className="flex items-center space-x-2">
          <Mic2 className="h-5 w-5" />
          <h3 className="font-bold">Push To Talk (WAV - Complete Chunks)</h3>
        </div>
        <div className="flex flex-col justify-center items-center space-y-2 min-h-[200px]">
          {connectionStatus !== "idle" && connectionStatus !== "recording" && (
            <div className="text-sm text-gray-500 mb-2">
              {connectionStatus === "connecting" ? "Establishing connection..." : `Status: ${connectionStatus}`}
            </div>
          )}

          {!isRecording ? (
            <Button 
              disabled={status !== "connected" || isConnecting || !encoderReady}
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
