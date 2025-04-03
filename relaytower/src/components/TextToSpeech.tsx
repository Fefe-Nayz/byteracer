import { useState } from "react";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { Card } from "./ui/card";
import { Input } from "./ui/input";
import { Button } from "./ui/button";
import { Megaphone, Play, Square } from "lucide-react";
import { useToast } from "@/hooks/use-toast";

export default function TextToSpeech() {
  const [text, setText] = useState("");
  const [isSending, setIsSending] = useState(false);
  const { status, speakText, stopTts, settings } = useWebSocket();
  const { toast } = useToast();
  
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!text.trim()) {
      return;
    }
    
    setIsSending(true);
    speakText(text);
    
    // Show toast notification
    toast({
      title: "Text sent to robot",
      description: text,
      duration: 3000,
    });
    
    // Reset after short delay
    setTimeout(() => {
      setIsSending(false);
      setText("");
    }, 1000);
  };
  
  const handleStopTts = () => {
    stopTts();
    
    // Show toast notification
    toast({
      title: "Speech stopped",
      description: "TTS speech has been stopped",
      duration: 2000,
    });
  };
  
  const ttsEnabled = settings?.sound.tts_enabled || false;
  
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center space-x-2">
          <Megaphone className="h-5 w-5" />
          <h3 className="font-bold">Text-to-Speech</h3>
        </div>
        <Button 
          variant="destructive" 
          size="sm"
          onClick={handleStopTts}
          disabled={status !== "connected" || !ttsEnabled}
        >
          <Square className="h-4 w-4 mr-1" />
          Stop
        </Button>
      </div>
      
      <form onSubmit={handleSubmit} className="flex space-x-2">
        <Input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Enter text for the robot to speak..."
          disabled={status !== "connected" || !ttsEnabled || isSending}
          className="flex-1"
        />
        <Button 
          type="submit" 
          disabled={status !== "connected" || !ttsEnabled || !text.trim() || isSending}
        >
          {isSending ? (
            <span className="animate-pulse">Sending...</span>
          ) : (
            <>
              <Play className="h-4 w-4 mr-2" />
              Speak
            </>
          )}
        </Button>
      </form>
      
      {!ttsEnabled && status === "connected" && (
        <p className="text-xs text-amber-600 mt-2">
          TTS is currently disabled. Enable it in Settings → Sound Settings.
        </p>
      )}
    </Card>
  );
}