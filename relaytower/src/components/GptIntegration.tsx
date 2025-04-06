import { useState, useEffect } from "react";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { Card } from "./ui/card";
import { Input } from "./ui/input";
import { Button } from "./ui/button";
import { Switch } from "./ui/switch";
import { BrainCircuit, Camera, Sparkles } from "lucide-react";
import { useToast } from "@/hooks/use-toast";

export default function GptIntegration() {
  const [prompt, setPrompt] = useState("");
  const [useCamera, setUseCamera] = useState(true);
  const [isProcessing, setIsProcessing] = useState(false);
  const [response, setResponse] = useState<string | null>(null);
  const { status, sendGptCommand } = useWebSocket();
  const { toast } = useToast();
  
  // Listen for GPT responses
  useEffect(() => {
    const handleGptResponse = (event: CustomEvent) => {
      if (event.detail) {
        setResponse(event.detail.response);
        setIsProcessing(false);
        
        toast({
          title: "GPT Response",
          description: "Received response from GPT",
          variant: "default",
        });
      }
    };
    
    // Add event listener
    window.addEventListener(
      "debug:gpt-response",
      handleGptResponse as EventListener
    );
    
    // Clean up
    return () => {
      window.removeEventListener(
        "debug:gpt-response",
        handleGptResponse as EventListener
      );
    };
  }, []);
  
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!prompt.trim()) {
      return;
    }
    
    setIsProcessing(true);
    setResponse(null);
    sendGptCommand(prompt, useCamera);
    
    toast({
      title: "Prompt sent to GPT",
      description: prompt,
      variant: "default",
    });
  };
  
  const examples = [
    "Make the robot dance",
    "Tell me what you see",
    "Follow the blue object",
    "Sing a song",
    "Tell a joke",
  ];
  
  const handleUseExample = (example: string) => {
    setPrompt(example);
  };
  
  return (
    <Card className="p-4">
      <div className="flex items-center space-x-2 mb-4">
        <BrainCircuit className="h-5 w-5" />
        <h3 className="font-bold">GPT Integration</h3>
      </div>
      
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Camera className="h-4 w-4" />
            <span className="text-sm">Use camera feed</span>
          </div>
          <Switch 
            checked={useCamera}
            onCheckedChange={setUseCamera}
            disabled={status !== "connected" || isProcessing}
          />
        </div>
        
        <Input
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Enter a prompt for the robot..."
          disabled={status !== "connected" || isProcessing}
          className="w-full"
        />
        
        <Button 
          type="submit" 
          className="w-full"
          disabled={status !== "connected" || !prompt.trim() || isProcessing}
        >
          {isProcessing ? (
            <span className="flex items-center">
              <span className="animate-pulse mr-2">
                <Sparkles className="h-4 w-4" />
              </span>
              Processing...
            </span>
          ) : (
            <span className="flex items-center">
              <Sparkles className="h-4 w-4 mr-2" />
              Send to GPT
            </span>
          )}
        </Button>
      </form>
      
      {response && (
        <div className="mt-4 p-3 bg-muted rounded-md text-sm">
          <div className="font-semibold mb-1">Response:</div>
          <div>{response}</div>
        </div>
      )}
      
      <div className="mt-4">
        <div className="text-xs font-medium mb-2">Examples:</div>
        <div className="flex flex-wrap gap-2">
          {examples.map((example) => (
            <Button
              key={example}
              variant="outline"
              size="sm"
              onClick={() => handleUseExample(example)}
              disabled={isProcessing}
              className="text-xs"
            >
              {example}
            </Button>
          ))}
        </div>
      </div>
      
      {status !== "connected" && (
        <p className="text-xs text-amber-600 mt-4">
          Connect to the robot to use GPT integration.
        </p>
      )}
    </Card>
  );
}