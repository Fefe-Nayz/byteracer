import { useState, useEffect } from "react";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { Card } from "./ui/card";
import { Input } from "./ui/input";
import { Button } from "./ui/button";
import { Switch } from "./ui/switch";
import { BrainCircuit, Camera, Sparkles, X, AlertTriangle, Loader2, CheckCircle2, Plus } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { Badge } from "./ui/badge";
import { Progress } from "./ui/progress";

export default function GptIntegration() {
  const [prompt, setPrompt] = useState("");
  const [useCamera, setUseCamera] = useState(true);
  const [isProcessing, setIsProcessing] = useState(false);
  const [response, setResponse] = useState<string | null>(null);
  const { status, sendGptCommand, cancelGptCommand, gptStatus, createNewThread } = useWebSocket();
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
  
  // Update processing state based on GPT status updates
  useEffect(() => {
    if (gptStatus) {
      // Set processing state based on the status
      if (gptStatus.status === "completed" || gptStatus.status === "error" || gptStatus.status === "cancelled") {
        setIsProcessing(false);
      } else {
        setIsProcessing(true);
      }
      
      // Show toast for important status updates
      if (gptStatus.status === "error") {
        toast({
          title: "GPT Error",
          description: gptStatus.message,
          variant: "destructive",
        });
      } else if (gptStatus.status === "cancelled") {
        toast({
          title: "GPT Command Cancelled",
          description: gptStatus.message,
          variant: "default",
        });
      } else if (gptStatus.status === "completed") {
        toast({
          title: "GPT Command Completed",
          description: gptStatus.message,
          variant: "default",
        });
      }
    }
  }, [gptStatus, toast]);
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
  
  const handleNewThread = () => {
    if (isProcessing) {
      return;
    }
    
    createNewThread();
    setResponse(null);
    
    toast({
      title: "New conversation started",
      description: "Created a new thread for GPT conversation",
      variant: "default",
    });
  };
  
  const handleCancelRequest = () => {
    cancelGptCommand();
    
    toast({
      title: "Cancelling GPT Command",
      description: "Requesting to cancel the current GPT command",
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
    <Card className="p-4">      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center space-x-2">
          <BrainCircuit className="h-5 w-5" />
          <h3 className="font-bold">GPT Integration</h3>
        </div>
        
        <Button
          size="sm"
          variant="outline"
          onClick={handleNewThread}
          disabled={status !== "connected" || isProcessing}
          className="h-8"
        >
          <Plus className="h-3.5 w-3.5 mr-1" />
          New Thread
        </Button>
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
        
        {/* Status display area */}
        {isProcessing && gptStatus && (
          <div className="my-3 space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                {gptStatus.status === "starting" || gptStatus.status === "progress" ? (
                  <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
                ) : gptStatus.status === "warning" ? (
                  <AlertTriangle className="h-4 w-4 text-amber-500" />
                ) : gptStatus.status === "error" ? (
                  <AlertTriangle className="h-4 w-4 text-red-500" />
                ) : (
                  <CheckCircle2 className="h-4 w-4 text-green-500" />
                )}
                <Badge variant={
                  gptStatus.status === "starting" || gptStatus.status === "progress" 
                    ? "default" 
                    : gptStatus.status === "error" 
                      ? "destructive" 
                      : gptStatus.status === "warning" || gptStatus.status === "cancelled"
                        ? "outline"
                        : "secondary"
                }>
                  {gptStatus.status}
                </Badge>
              </div>
              
              {/* Cancel button */}
              {(gptStatus.status === "starting" || gptStatus.status === "progress") && (
                <Button 
                  size="sm" 
                  variant="outline" 
                  onClick={handleCancelRequest}
                  className="h-7 px-2"
                >
                  <X className="h-3.5 w-3.5 mr-1" />
                  Cancel
                </Button>
              )}
            </div>
            
            <Progress value={
              gptStatus.status === "starting" 
                ? 10 
                : gptStatus.status === "progress" 
                  ? 50 
                  : gptStatus.status === "completed" 
                    ? 100 
                    : 0
            } className="h-1.5" />
            
            <p className="text-xs text-muted-foreground">
              {gptStatus.message}
            </p>
          </div>
        )}
        
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
      
      {response && !isProcessing && (
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