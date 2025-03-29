import { useState } from "react";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { Card } from "./ui/card";
import { Button } from "./ui/button";
import { Music } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { VolumeX } from "lucide-react";

export default function SoundEffects() {
  const [isPlaying, setIsPlaying] = useState<string | null>(null);
  const { status, playSound, settings } = useWebSocket();
  const { toast } = useToast();
  
  const handlePlaySound = (sound: string) => {
    if (isPlaying) return;
    
    setIsPlaying(sound);
    playSound(sound);
    
    // Show toast notification
    toast({
      title: "Playing sound",
      description: `Playing ${sound} sound`,
      duration: 2000,
    });
    
    // Reset after delay (assuming most sounds are short)
    setTimeout(() => {
      setIsPlaying(null);
    }, 2000);
  };
  
  // Define available sound effects
  const soundEffects = [
    { id: "fart", name: "Fart", icon: "💨" },
    { id: "horn", name: "Horn", icon: "📢" },
    { id: "alarm", name: "Alarm", icon: "🚨" },
    { id: "wow", name: "Wow", icon: "🤩" },
    { id: "laugh", name: "Laugh", icon: "😂" },
    { id: "bruh", name: "Bruh", icon: "😑" },
    { id: "nope", name: "Nope", icon: "❌" },
    { id: "yeet", name: "Yeet", icon: "🚀" },
  ];
  
  const soundEnabled = settings?.sound.enabled || false;
  
  return (
    <Card className="p-4">
      <div className="flex items-center space-x-2 mb-3">
        <Music className="h-5 w-5" />
        <h3 className="font-bold">Sound Effects</h3>
      </div>
      
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {soundEffects.map(sound => (
          <Button
            key={sound.id}
            variant="outline"
            onClick={() => handlePlaySound(sound.id)}
            disabled={status !== "connected" || !soundEnabled || !!isPlaying}
            className={`h-auto py-3 ${isPlaying === sound.id ? 'bg-primary/20' : ''}`}
          >
            <div className="flex flex-col items-center">
              <span className="text-xl mb-1">{sound.icon}</span>
              <span className="text-xs">{sound.name}</span>
            </div>
          </Button>
        ))}
      </div>
      
      {!soundEnabled && status === "connected" && (
        <div className="flex items-center mt-3 text-xs text-amber-600">
          <VolumeX className="h-3 w-3 mr-1" />
          Sound is currently disabled. Enable it in Settings.
        </div>
      )}
    </Card>
  );
}