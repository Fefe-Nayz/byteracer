import { useState, useEffect } from "react";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { Card } from "./ui/card";
import { Input } from "./ui/input";
import { Button } from "./ui/button";
import { Megaphone, Play, Square, Globe } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";

export default function TextToSpeech() {
  const [text, setText] = useState("");
  const [language, setLanguage] = useState("");
  const { status, speakText, stopTts, settings, requestSettings } = useWebSocket();
  const { toast } = useToast();

  // Request settings only once when component mounts
  useEffect(() => {
    requestSettings();
  }, [requestSettings]);

  // Set default language from settings when component loads or settings change
  useEffect(() => {
    if (settings?.sound.tts_language) {
      setLanguage(settings.sound.tts_language);
    }
  }, [settings]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    if (!text.trim()) {
      return;
    }


    speakText(text, language);

    toast({
      title: "Text sent to robot",
      description: text,
      duration: 3000,
    });

    // Clear text input but don't block further input
    setText("");
  };

  const handleStopTts = () => {
    stopTts();

    toast({
      title: "Speech stopped",
      description: "TTS speech has been stopped",
      duration: 2000,
    });
  };

  const ttsEnabled = settings?.sound.tts_enabled || false;

  const languages = [
    { value: "en-US", label: "English (US)" },
    { value: "en-GB", label: "English (UK)" },
    { value: "fr-FR", label: "French" },
    { value: "de-DE", label: "German" },
    { value: "es-ES", label: "Spanish" },
    { value: "it-IT", label: "Italian" },
  ];

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

      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="flex space-x-2">
          <Input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Enter text for the robot to speak..."
            disabled={status !== "connected" || !ttsEnabled}
            className="flex-1"
          />
          <Button
            type="submit"
            disabled={
              status !== "connected" || !ttsEnabled || !text.trim()
            }
          >
            <>
              <Play className="h-4 w-4 mr-2" />
              Speak
            </>
          </Button>
        </div>
        <div className="flex items-center space-x-2">
          <Globe className="h-5 w-5" />
          <Select
            value={language}
            onValueChange={(value) => setLanguage(value)}
            disabled={status !== "connected" || !ttsEnabled}
          >
            <SelectTrigger className="w-full">
              <SelectValue placeholder="Select language" />
            </SelectTrigger>
            <SelectContent>
              {languages.map((lang) => (
                <SelectItem key={lang.value} value={lang.value}>
                  {lang.label}
                  {lang.value === settings?.sound.tts_language && " (Default)"}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </form>

      {!ttsEnabled && status === "connected" && (
        <p className="text-xs text-amber-600 mt-2">
          TTS is currently disabled. Enable it in Settings → Sound Settings.
        </p>
      )}
    </Card>
  );
}