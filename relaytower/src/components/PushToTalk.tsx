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
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const opusChunks = useRef<Blob[]>([]);

  // Check if MediaRecorder is available and supports opus
  useEffect(() => {
    const checkMediaRecorderSupport = async () => {
      if (!window.MediaRecorder) {
        setErrorMessage("Votre navigateur ne supporte pas MediaRecorder");
        return false;
      }
      
      try {
        // Get a temporary stream to check codec support
        const tempStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        
        // Check if opus codec is supported
        const mimeType = 'audio/webm;codecs=opus';
        const isSupported = MediaRecorder.isTypeSupported(mimeType);
        
        // Stop all tracks
        tempStream.getTracks().forEach(track => track.stop());
        
        if (!isSupported) {
          setErrorMessage("Le codec Opus n'est pas supporté par votre navigateur");
          return false;
        }
        
        setIsReady(true);
        return true;
      } catch (err) {
        console.error("Erreur lors de la vérification du support MediaRecorder:", err);
        setErrorMessage("Erreur lors de l'initialisation de l'audio");
        return false;
      }
    };
    
    checkMediaRecorderSupport();
  }, []);

  const startTalk = async () => {
    if (!isReady || status !== "connected") {
      console.error("Pas prêt ou WebSocket non connecté");
      return;
    }

    try {
      // Get microphone stream
      console.log("Demande d'accès au microphone...");
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        }, 
        video: false 
      });
      streamRef.current = stream;
      console.log("Accès au microphone accordé");
      
      // Clear previous chunks
      opusChunks.current = [];
      
      // Create MediaRecorder with opus codec
      const mimeType = 'audio/webm;codecs=opus';
      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: mimeType,
        audioBitsPerSecond: 32000 // 32 kbps pour l'audio voix
      });
      mediaRecorderRef.current = mediaRecorder;
      
      // Handle data available event
      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          opusChunks.current.push(event.data);
          
          // Convert to binary data and send via WebSocket
          const reader = new FileReader();
          reader.onloadend = () => {
            if (reader.result && typeof reader.result !== 'string') {
              const audioData = new Uint8Array(reader.result);
              
              // Send to WebSocket
              sendAudioStream("opus", "webm", Array.from(audioData)
              );
              
              console.log(`Envoi d'un paquet Opus de ${audioData.length} octets`);
            }
          };
          reader.readAsArrayBuffer(event.data);
        }
      };
      
      // Start recording with 500ms timeslices
      mediaRecorder.start(500);
      console.log("Enregistrement avec Opus commencé");
      
      setIsTalking(true);
    } catch (error) {
      console.error("Erreur lors du démarrage de l'enregistrement:", error);
      setErrorMessage(error instanceof Error ? error.message : "Erreur inconnue");
      setIsTalking(false);
    }
  };

  const stopTalk = () => {
    setIsTalking(false);
    console.log("Microphone désactivé");

    // Stop MediaRecorder
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }

    // Stop the stream tracks
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }
    
    // Clear chunks
    opusChunks.current = [];
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