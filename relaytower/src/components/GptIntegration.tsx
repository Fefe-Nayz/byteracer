import { useState, useEffect } from "react";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { useToast } from "@/hooks/use-toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Progress } from "@/components/ui/progress";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { 
  BrainCircuit, 
  Camera, 
  Code, 
  Plus, 
  Terminal, 
  RotateCw, 
  X, 
  Loader2, 
  AlertTriangle, 
  CheckCircle2, 
  Sparkles,
  Mic,
  MicOff,
  Volume2
} from "lucide-react";

interface GptStatusData {
  token_usage?: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
  execution_details?: {
    type: string;
    summary: string;
  };
  current_step?: number;
  total_steps?: number;
  error_type?: string;
  details?: string;
  traceback?: string;
  error_details?: string;
  mic_status?: string;
  response_content?: {
    action_type: string;
    text: string;
    language: string;
    python_script?: string;    predefined_functions?: Array<{
      function_name: string;
      parameters: Record<string, unknown>;
    }>;
    motor_sequence?: Array<{
      motor_id: string;
      actions: Array<{
        timestamp: number;
        command: string;
        value: number;
      }>;
    }>;
  };
  full_response?: Record<string, unknown>;
}

export default function GptIntegration() {
  const [prompt, setPrompt] = useState("");
  const [useCamera, setUseCamera] = useState(false);
  const [useAiVoice, setUseAiVoice] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [response, setResponse] = useState<string | null>(null);
  const [responseDetails, setResponseDetails] = useState<GptStatusData | null>(null);
  const [actionType, setActionType] = useState<string | null>(null);
  const [tokenUsage, setTokenUsage] = useState<{prompt_tokens: number, completion_tokens: number, total_tokens: number} | null>(null);
  const [executionProgress, setExecutionProgress] = useState<{current: number, total: number} | null>(null);
  const [executionHistory, setExecutionHistory] = useState<Array<{timestamp: number, message: string, status: string}>>([]);
  const [activeTab, setActiveTab] = useState<string>("text");
  const [isConversationActive, setIsConversationActive] = useState(false);
  const [recognizedText, setRecognizedText] = useState<string | null>(null);
  const [isMicReady, setIsMicReady] = useState(false);
  const { 
    status, 
    sendGptCommand, 
    cancelGptCommand, 
    gptStatus, 
    createNewThread
  } = useWebSocket();
  
  const { toast } = useToast();

  console.log(isMicReady, "Mic Ready State");
  
  // Listen for GPT responses and speech recognition events
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
    
    const handleSpeechRecognition = (event: CustomEvent) => {
      if (event.detail && event.detail.text) {
        setRecognizedText(event.detail.text);
      }
    };
    
    // Add event listeners
    window.addEventListener(
      "debug:gpt-response",
      handleGptResponse as EventListener
    );
    
    window.addEventListener(
      "speech:recognized",
      handleSpeechRecognition as EventListener
    );
    
    // Clean up
    return () => {
      window.removeEventListener(
        "debug:gpt-response",
        handleGptResponse as EventListener
      );
      
      window.removeEventListener(
        "speech:recognized",
        handleSpeechRecognition as EventListener
      );
    };
  }, [isConversationActive, toast]);
  
  // Update processing state based on GPT status updates
  useEffect(() => {
    if (gptStatus) {
      console.log("GPT Status Update:", gptStatus, actionType);
      // Set processing state based on the status        
      if (gptStatus.status === "completed" || gptStatus.status === "error" || gptStatus.status === "cancelled") {
        setIsProcessing(false);
        
        // End conversation mode if it's active and status is cancelled
        if (gptStatus.status === "cancelled" && isConversationActive) {
          setIsConversationActive(false);
          setRecognizedText(null);
          setIsMicReady(false);
        }
      } else {
        setIsProcessing(true);
        
        // Check mic status
        if (gptStatus.mic_status) {
          if (gptStatus.mic_status === "ready") {
            setIsMicReady(true);
          } else if (gptStatus.mic_status === "waiting") {
            setIsMicReady(false);
            setRecognizedText(null);
          }
        }
      }
      
      // Add to execution history
      setExecutionHistory(prev => [...prev, {
        timestamp: gptStatus.timestamp || Date.now(),
        message: gptStatus.message,
        status: gptStatus.status
      }]);
      
      // Process additional data if available
      if (gptStatus) {
        // Update token usage if available
        if (gptStatus.token_usage) {
          setTokenUsage(gptStatus.token_usage);
        }
        
        // Update response content if available (from our extended API)
        if (gptStatus.response_content) {
          setActionType(gptStatus.response_content.action_type);
          setResponse(gptStatus.response_content.text);
        }
        
        // Update execution details if available
        if (gptStatus.execution_details) {
          setActionType(gptStatus.execution_details.type);
          setResponseDetails(prev => ({
            ...prev,
            execution_details: gptStatus.execution_details
          }));
        }
        
        // Update execution progress if available
        if (gptStatus.current_step && gptStatus.total_steps) {
          setExecutionProgress({
            current: gptStatus.current_step,
            total: gptStatus.total_steps
          });
        }
        
        // Store all response details
        setResponseDetails(prev => ({
          ...prev,
          ...gptStatus
        }));
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
    setResponseDetails(null);
    setActionType(null);
    setTokenUsage(null);
    setExecutionProgress(null);
    setExecutionHistory([]);
    
    // Call sendGptCommand with useAiVoice parameter
    try {
      // Pass all parameters: prompt, useCamera, useAiVoice, and conversationMode=false
      sendGptCommand(prompt, useCamera, useAiVoice, false);
    } catch (err) {
      console.error("Error sending GPT command:", err);
    }
    
    toast({
      title: "Prompt sent to GPT",
      description: prompt,
      variant: "default",
    });
  };
  
  const toggleConversation = () => {
    if (!isConversationActive) {
      startConversation();
    } else {
      stopConversation();
    }
  };
  
  const startConversation = () => {
    setIsConversationActive(true);
    
    // Create a new thread for the conversation
    createNewThread();
    
    // Start conversation mode with robot handling the recording and STT
    // We pass an empty prompt since the robot will ignore it in conversation mode
    try {
      // Pass all parameters with conversationMode=true
      sendGptCommand("", useCamera, useAiVoice, true);
    } catch (err) {
      console.error("Error starting conversation mode:", err);
    }
    
    toast({
      title: "Conversation Mode Started",
      description: "Listening for your voice input...",
      variant: "default",
    });
  };
  
  const stopConversation = () => {
    setIsConversationActive(false);
    setRecognizedText(null);
    
    // Cancel the conversation on the robot with conversationMode=true
    cancelGptCommand(true);
    
    toast({
      title: "Conversation Mode Ended",
      description: "Voice conversation has been stopped",
      variant: "default",
    });
  };
  
  const handleNewThread = () => {
    if (isProcessing) {
      return;
    }
    
    createNewThread();
    setResponse(null);
    setResponseDetails(null);
    setActionType(null);
    setTokenUsage(null);
    setExecutionProgress(null);
    setExecutionHistory([]);
    
    toast({
      title: "New conversation started",
      description: "Created a new thread for GPT conversation",
      variant: "default",
    });
  };
    const handleCancelRequest = () => {
    // Pass true if in conversation mode, otherwise false
    cancelGptCommand(isConversationActive);
    
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
  
  // Function to render action type badge
  const renderActionTypeBadge = (type: string | null) => {
    if (!type) return null;
    
    let icon = <Code className="h-3.5 w-3.5 mr-1" />;
    let label = type;
    let variant: "default" | "secondary" | "outline" = "default";
    
    switch(type) {
      case "python_script":
        icon = <Terminal className="h-3.5 w-3.5 mr-1" />;
        label = "Python Script";
        variant = "secondary";
        break;
      case "predefined_function":
        icon = <RotateCw className="h-3.5 w-3.5 mr-1" />;
        label = "Function Call";
        variant = "outline";
        break;
      case "motor_sequence":
        icon = <RotateCw className="h-3.5 w-3.5 mr-1" />;
        label = "Motor Sequence";
        variant = "outline";
        break;
      case "none":
        icon = <BrainCircuit className="h-3.5 w-3.5 mr-1" />;
        label = "Text Response";
        variant = "default";
        break;
    }
    
    return (
      <Badge variant={variant} className="mb-2">
        {icon}
        {label}
      </Badge>
    );
  };
  
  return (
    <Card className="p-4">      
      <div className="flex items-center justify-between mb-4">
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
      
      {/* Input Settings Options */}
      <div className="flex flex-col space-y-3 mb-4">
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
        
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Volume2 className="h-4 w-4" />
            <span className="text-sm">Use AI voice</span>
          </div>
          <Switch 
            checked={useAiVoice}
            onCheckedChange={setUseAiVoice}
            disabled={status !== "connected" || isProcessing}
          />
        </div>
      </div>
      
      {/* Tab interface for text/conversation modes */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid w-full grid-cols-2 mb-4">
          <TabsTrigger value="text">Text Input</TabsTrigger>
          <TabsTrigger value="conversation">Voice Conversation</TabsTrigger>
        </TabsList>
        
        <TabsContent value="text">
          <form onSubmit={handleSubmit} className="space-y-4">
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
            
            {/* Examples Section */}
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
          </form>
        </TabsContent>
        
        <TabsContent value="conversation">
          <div className="space-y-4">
            <div className="bg-muted rounded-md p-4 flex flex-col items-center justify-center min-h-[120px] text-center">              {isConversationActive ? (
                <div className="flex flex-col items-center space-y-2">
                  <div className="relative">
                    <div className="absolute -inset-1 rounded-full bg-primary/20 animate-pulse"></div>
                    <Mic className="h-12 w-12 text-primary relative z-10" />
                  </div>
                  {gptStatus && isMicReady ? (
                    <p className="text-sm font-medium">Listening for your voice...</p>
                  ) : (
                    <p className="text-sm font-medium">Initializing microphone...</p>
                  )}
                  {recognizedText && (
                    <p className="text-sm text-muted-foreground mt-2 italic">&quot;{recognizedText}&quot;</p>
                  )}
                </div>
              ) : (
                <div className="flex flex-col items-center space-y-2">
                  <MicOff className="h-12 w-12 text-muted-foreground" />
                  <p className="text-sm text-muted-foreground">Start a voice conversation with the robot</p>
                </div>
              )}
            </div>
            
            <Button
              onClick={toggleConversation}
              disabled={status !== "connected" || isProcessing}
              variant={isConversationActive ? "destructive" : "default"}
              className="w-full"
            >
              {isConversationActive ? (
                <span className="flex items-center">
                  <MicOff className="h-4 w-4 mr-2" />
                  End Conversation
                </span>
              ) : (
                <span className="flex items-center">
                  <Mic className="h-4 w-4 mr-2" />
                  Start Conversation
                </span>
              )}
            </Button>
          </div>
        </TabsContent>
      </Tabs>
      
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
          
          {/* Show progress based on execution status */}
          {executionProgress ? (
            <Progress 
              value={(executionProgress.current / executionProgress.total) * 100} 
              className="h-1.5" 
            />
          ) : (
            <Progress value={
              gptStatus.status === "starting" 
                ? 10 
                : gptStatus.status === "progress" 
                  ? 50 
                  : gptStatus.status === "completed" 
                    ? 100 
                    : 0
            } className="h-1.5" />
          )}
          
          <p className="text-xs text-muted-foreground">
            {gptStatus.message}
            {executionProgress && (
              <span className="text-xs ml-1 opacity-75">
                (Step {executionProgress.current} of {executionProgress.total})
              </span>
            )}
          </p>
        </div>
      )}
      
      {/* Enhanced response display */}
      {(response || responseDetails) && !isProcessing && (
        <div className="mt-4">
          <Tabs defaultValue="response" className="w-full">
            <TabsList className="grid w-full grid-cols-4">
              <TabsTrigger value="response">Response</TabsTrigger>
              <TabsTrigger value="code" disabled={!responseDetails?.response_content?.python_script}>Code</TabsTrigger>
              <TabsTrigger value="functions" disabled={!responseDetails?.response_content?.predefined_functions?.length}>Functions</TabsTrigger>
              <TabsTrigger value="details">Details</TabsTrigger>
            </TabsList>
            
            {/* Text Response Tab */}
            <TabsContent value="response" className="space-y-2 py-2">
              {responseDetails?.response_content?.action_type && renderActionTypeBadge(responseDetails.response_content.action_type)}
              <div className="p-3 bg-muted rounded-md text-sm whitespace-pre-wrap">
                {responseDetails?.response_content?.text || response || "No response text available"}
              </div>
            </TabsContent>
            
            {/* Python Code Tab */}
            <TabsContent value="code" className="space-y-2 py-2">
              {responseDetails?.response_content?.python_script && (
                <div className="rounded-md border overflow-hidden">
                  <div className="p-2 bg-slate-100 dark:bg-slate-800 border-b flex items-center">
                    <Terminal className="h-4 w-4 mr-2" />
                    <span className="font-medium text-sm">Python Script</span>
                  </div>
                  <div className="p-4 bg-slate-50 dark:bg-slate-900 font-mono text-sm overflow-x-auto">
                    <pre>{responseDetails.response_content.python_script}</pre>
                  </div>
                </div>
              )}
            </TabsContent>
            
            {/* Function Calls Tab */}
            <TabsContent value="functions" className="space-y-3 py-2">
              {responseDetails?.response_content?.predefined_functions?.map((func, index) => (
                <div key={index} className="rounded-md border overflow-hidden">
                  <div className="p-2 bg-slate-100 dark:bg-slate-800 border-b flex items-center">
                    <RotateCw className="h-4 w-4 mr-2" />
                    <span className="font-medium text-sm">{func.function_name}()</span>
                  </div>
                  <div className="p-3 font-mono text-sm overflow-x-auto bg-slate-50 dark:bg-slate-900">
                    <pre>{JSON.stringify(func.parameters, null, 2)}</pre>
                  </div>
                </div>
              ))}
            </TabsContent>
            
            <TabsContent value="details" className="space-y-3 py-2">
              {/* Token usage */}
              {tokenUsage && (
                <div className="rounded-md border p-3">
                  <h4 className="font-medium mb-2 text-sm">Token Usage</h4>
                  <div className="grid grid-cols-3 gap-2 text-sm">
                    <div className="flex flex-col">
                      <span className="text-gray-500 dark:text-gray-400">Prompt</span>
                      <span className="font-mono">{tokenUsage.prompt_tokens}</span>
                    </div>
                    <div className="flex flex-col">
                      <span className="text-gray-500 dark:text-gray-400">Completion</span>
                      <span className="font-mono">{tokenUsage.completion_tokens}</span>
                    </div>
                    <div className="flex flex-col">
                      <span className="text-gray-500 dark:text-gray-400">Total</span>
                      <span className="font-mono">{tokenUsage.total_tokens}</span>
                    </div>
                  </div>
                </div>
              )}
              
              {/* Motor Sequence Display */}
              {responseDetails?.response_content?.motor_sequence && 
               responseDetails.response_content.motor_sequence.length > 0 && (
                <div className="rounded-md border p-3">
                  <h4 className="font-medium mb-2 text-sm">Motor Sequence</h4>
                  <div className="space-y-3">
                    {responseDetails.response_content.motor_sequence.map((motor, idx) => (
                      <div key={idx} className="border rounded-sm p-2">
                        <p className="font-medium text-sm mb-1">Motor: {motor.motor_id}</p>
                        <div className="text-xs overflow-x-auto">
                          <table className="min-w-full">
                            <thead>
                              <tr className="border-b">
                                <th className="text-left p-1">Time (s)</th>
                                <th className="text-left p-1">Command</th>
                                <th className="text-left p-1">Value</th>
                              </tr>
                            </thead>
                            <tbody>
                              {motor.actions.map((action, actionIdx) => (
                                <tr key={actionIdx} className="even:bg-gray-50 dark:even:bg-gray-800">
                                  <td className="p-1">{action.timestamp.toFixed(2)}</td>
                                  <td className="p-1">{action.command}</td>
                                  <td className="p-1">{action.value}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              
              {/* Full Response (for debugging) */}
              {responseDetails?.full_response && (
                <Collapsible className="w-full">
                  <CollapsibleTrigger className="flex w-full justify-between items-center p-2 bg-muted rounded-md text-sm font-medium">
                    <span>Full Response Data</span>
                    <Plus className="h-4 w-4" />
                  </CollapsibleTrigger>
                  <CollapsibleContent className="p-2 text-xs">
                    <div className="p-2 bg-slate-50 dark:bg-slate-900 font-mono text-xs overflow-x-auto rounded-md">
                      <pre>{JSON.stringify(responseDetails.full_response, null, 2)}</pre>
                    </div>
                  </CollapsibleContent>
                </Collapsible>
              )}
              
              {/* Error details and traceback */}
              {(gptStatus?.status === "error" && (gptStatus.traceback || gptStatus.error_details)) && (
                <div className="p-3 bg-red-50 dark:bg-red-950/20 rounded-md text-sm border border-red-200 dark:border-red-900 mb-2">
                  <div className="font-medium mb-1 text-red-600 dark:text-red-400">Python Script Error</div>
                  {gptStatus.error_details && (
                    <div className="text-red-700 dark:text-red-300 mb-2">{gptStatus.error_details}</div>
                  )}
                  {gptStatus.traceback && (
                    <div className="bg-slate-100 dark:bg-slate-900 p-2 rounded font-mono text-xs overflow-x-auto max-h-60">
                      <pre>{gptStatus.traceback}</pre>
                    </div>
                  )}
                </div>
              )}
              
              {/* Execution History */}
              <Collapsible className="w-full">
                <CollapsibleTrigger className="flex w-full justify-between items-center p-2 bg-muted rounded-md text-sm font-medium">
                  <span>Execution History ({executionHistory.length})</span>
                  <Plus className="h-4 w-4" />
                </CollapsibleTrigger>
                <CollapsibleContent className="max-h-40 overflow-y-auto">
                  {executionHistory.length > 0 ? (
                    <div className="space-y-1 p-2">
                      {executionHistory.map((item, idx) => (
                        <div key={idx} className="flex items-start space-x-2 text-xs p-1 border-b border-muted">
                          <div className="min-w-16 text-muted-foreground">
                            {new Date(item.timestamp).toLocaleTimeString()}
                          </div>
                          <Badge 
                            variant={
                              item.status === "error" 
                                ? "destructive" 
                                : item.status === "completed"
                                  ? "secondary"
                                  : "outline"
                            }
                            className="h-5 px-1"
                          >
                            {item.status}
                          </Badge>
                          <div>{item.message}</div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-sm text-muted-foreground p-3">No execution history available</div>
                  )}
                </CollapsibleContent>
              </Collapsible>
            </TabsContent>
          </Tabs>
        </div>
      )}
      
      {status !== "connected" && (
        <p className="text-xs text-amber-600 mt-4">
          Connect to the robot to use GPT integration.
        </p>
      )}
    </Card>
  );
}