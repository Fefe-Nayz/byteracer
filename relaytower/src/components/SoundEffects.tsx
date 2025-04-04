import { useEffect } from "react";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { Card } from "./ui/card";
import { Button } from "./ui/button";
import { Music, VolumeX, Gamepad, Square } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { useLocalStorage } from "@/hooks/useLocalStorage";

export default function SoundEffects() {
  const [selectedSound, setSelectedSound] = useLocalStorage<string>("gamepad-selected-sound", "fart");
  const { status, playSound, stopSound, settings } = useWebSocket();
  const { toast } = useToast();
  
  const handlePlaySound = (sound: string) => {
    playSound(sound);
    
    // Show toast notification
    toast({
      title: "Playing sound",
      description: `Playing ${sound} sound`,
      duration: 2000,
    });
  };
  
  const handleStopSound = () => {
    stopSound();
    
    // Show toast notification
    toast({
      title: "Sounds stopped",
      description: "All sounds have been stopped",
      duration: 2000,
    });
  };
  
  const handleSelectSound = (sound: string) => {
    setSelectedSound(sound);
    
    // Show toast notification
    toast({
      title: "Quick Sound Selected",
      description: `"${sound}" will play when using gamepad action button`,
      duration: 2000,
    });
  };
  
  // Expose selected sound for GamepadInputHandler through window event
  useEffect(() => {
    // Create custom event to share selected sound with GamepadInputHandler
    window.dispatchEvent(
      new CustomEvent("sound:selected-update", {
        detail: { selectedSound },
      })
    );
  }, [selectedSound]);
  
  // Define available sound effects
  const soundEffects = [
    { id: "fart", name: "Fart", icon: "💨" },
    { id: "klaxon", name: "Klaxon", icon: "📢" },
    { id: "alarm", name: "Alarm", icon: "🚨" },
    { id: "wow", name: "Wow", icon: "🤩" },
    { id: "laugh", name: "Laugh", icon: "😂" },
    { id: "bruh", name: "Bruh", icon: "😑" },
    { id: "nope", name: "Nope", icon: "❌" },
    { id:"lingango", name: "Lingango", icon: "🗣️" },
    { id: "cailloux", name: "Cailloux", icon: "🪨" },
    { id: "fave", name: "Favéé", icon: "🎤" },
    { id: "pipe", name: "Pipe", icon: "🔩" },
    { id: "tuile", name: "Une Tuile", icon: "🧱" },
  ];
  
  const soundEnabled = settings?.sound.enabled || false;
  
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center space-x-2">
          <Music className="h-5 w-5" />
          <h3 className="font-bold">Sound Effects</h3>
        </div>
        <div className="flex items-center space-x-2">
          <div className="text-xs flex items-center">
            <Gamepad className="h-4 w-4 mr-1" />
            <span>Quick: {selectedSound}</span>
          </div>
          <Button 
            variant="destructive" 
            size="sm"
            onClick={handleStopSound}
            disabled={status !== "connected" || !soundEnabled}
            className="ml-2"
          >
            <Square className="h-4 w-4 mr-1" />
            Stop
          </Button>
        </div>
      </div>
      
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {soundEffects.map(sound => (
          <Button
            key={sound.id}
            variant="outline"
            onClick={() => handlePlaySound(sound.id)}
            onContextMenu={(e) => {
              e.preventDefault();
              handleSelectSound(sound.id);
              return false;
            }}
            disabled={status !== "connected" || !soundEnabled }
            className={`h-auto py-3 relative ${selectedSound === sound.id ? 'border-2 border-primary' : ''}`}
          >
            <div className="flex flex-col items-center">
              <span className="text-xl mb-1">{sound.icon}</span>
              <span className="text-xs">{sound.name}</span>
              {selectedSound === sound.id && (
                <span className="absolute top-0 right-0 p-1">
                  <Gamepad className="h-3 w-3 text-primary" />
                </span>
              )}
            </div>
          </Button>
        ))}
      </div>
      
      <div className="mt-3 text-xs text-muted-foreground">
        <p>Right-click to set as gamepad quick sound</p>
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