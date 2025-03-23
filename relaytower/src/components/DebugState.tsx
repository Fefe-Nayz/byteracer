"use client";
import { useGamepadContext } from "@/contexts/GamepadContext";
import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs";
import {
  CollapsibleContent,
  Collapsible,
  CollapsibleTrigger,
} from "./ui/collapsible";
import { Button } from "./ui/button";
import {
  ChevronDown,
  Clock,
  Send,
  Download,
  Activity,
  Info,
  Settings,
  AlertCircle,
} from "lucide-react";

// Define proper types instead of any
interface WebSocketMessage {
  name: string;
  data: Record<string, unknown>;
  createdAt: number;
}

type MessageData = WebSocketMessage;
type MessageEntry = { time: Date; data: MessageData | null };

// Track WebSocket messages globally
let lastWsSent: MessageEntry | null = null;
let lastWsReceived: MessageEntry | null = null;
let lastGamepadInputMessage: MessageEntry | null = null;
let lastPingMessage: MessageEntry | null = null;
let wsConnectTime: Date | null = null;
let wsDisconnectTime: Date | null = null;
let errorLogs: {
  time: Date;
  message: string;
  details?: Record<string, unknown>;
}[] = [];

// Update the trackWsMessage function to store type-specific messages
export function trackWsMessage(
  direction: "sent" | "received",
  data: MessageData | null
) {
  if (direction === "sent") {
    lastWsSent = { time: new Date(), data };

    // Store type-specific messages
    if (data && data.name === "gamepad_input") {
      lastGamepadInputMessage = { time: new Date(), data };
    } else if (data && data.name === "ping") {
      lastPingMessage = { time: new Date(), data };
    }
  } else {
    lastWsReceived = { time: new Date(), data };
  }
}

// Add this to track connection events
export function trackWsConnection(type: "connect" | "disconnect") {
  if (type === "connect") {
    wsConnectTime = new Date();
  } else {
    wsDisconnectTime = new Date();
  }
}

// Add this to log errors
export function logError(message: string, details?: Record<string, unknown>) {
  errorLogs.unshift({ time: new Date(), message, details });
  // Keep only last 100 errors
  if (errorLogs.length > 100) errorLogs.pop();
}

export default function DebugState() {
  const {
    availableGamepads,
    selectedGamepadId,
    connected,
    listeningFor,
    pressedInputs,
    axisValues,
    mappings,
  } = useGamepadContext();

  const [now, setNow] = useState(new Date());
  const [performanceStats, setPerformanceStats] = useState({
    fps: 0,
    lastFrameTime: 0,
    updateTimes: [] as number[],
  });
  const [isClient, setIsClient] = useState(false);

  // Check if we're in the browser environment
  useEffect(() => {
    setIsClient(true);
  }, []);

  // Update time every second to show relative times
  useEffect(() => {
    if (!isClient) return;

    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, [isClient]);

  // Monitor performance
  useEffect(() => {
    if (!isClient) return;

    let frameCount = 0;
    let lastTime = performance.now();
    const frameTimes: number[] = [];

    const measurePerformance = () => {
      const now = performance.now();
      const delta = now - lastTime;
      lastTime = now;

      frameCount++;
      frameTimes.push(delta);

      // Keep only 60 frames of history
      if (frameTimes.length > 60) {
        frameTimes.shift();
      }

      // Update stats every second
      if (frameCount % 60 === 0) {
        const avgTime =
          frameTimes.reduce((sum, t) => sum + t, 0) / frameTimes.length;
        setPerformanceStats({
          fps: Math.round(1000 / avgTime),
          lastFrameTime: Math.round(delta),
          updateTimes: frameTimes,
        });
      }

      requestAnimationFrame(measurePerformance);
    };

    const frameId = requestAnimationFrame(measurePerformance);
    return () => cancelAnimationFrame(frameId);
  }, [isClient]);

  // Prevent rendering on server
  if (!isClient) return null;

  const formatTime = (date: Date | null) => {
    if (!date) return "N/A";
    const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    return `${Math.floor(seconds / 3600)}h ago`;
  };

  // Convert pressedInputs Set to array for display
  const pressedInputsArray = Array.from(pressedInputs || []);

  return (
    <Card className="my-4">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <Activity size={16} />
          DEBUG CONSOLE
        </CardTitle>
      </CardHeader>
      <CardContent className="text-xs font-mono">
        <Tabs defaultValue="status">
          <TabsList className="mb-4">
            <TabsTrigger value="status" className="text-xs">
              <Info size={14} className="mr-1" /> Status
            </TabsTrigger>
            <TabsTrigger value="websocket" className="text-xs">
              <Send size={14} className="mr-1" /> WebSocket
            </TabsTrigger>
            <TabsTrigger value="gamepad" className="text-xs">
              <Settings size={14} className="mr-1" /> Gamepad
            </TabsTrigger>
            <TabsTrigger value="errors" className="text-xs">
              <AlertCircle size={14} className="mr-1" /> Errors
            </TabsTrigger>
            <TabsTrigger value="perf" className="text-xs">
              <Activity size={14} className="mr-1" /> Performance
            </TabsTrigger>
          </TabsList>

          <TabsContent value="status" className="space-y-2">
            <div className="grid grid-cols-2 gap-x-4 gap-y-1">
              <div className="flex justify-between">
                <span className="text-muted-foreground">
                  Available gamepads:
                </span>{" "}
                <span>{availableGamepads.length}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Selected ID:</span>{" "}
                <span>{selectedGamepadId || "none"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Connected:</span>{" "}
                <span>{connected ? "yes" : "no"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Listening for:</span>{" "}
                <span>{listeningFor || "none"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">WS Connected:</span>{" "}
                <span>{wsConnectTime ? "yes" : "no"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Last connect:</span>{" "}
                <span>{formatTime(wsConnectTime)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Last disconnect:</span>{" "}
                <span>{formatTime(wsDisconnectTime)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Active inputs:</span>{" "}
                <span>{pressedInputsArray.length}</span>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="websocket">
            <div className="space-y-4">
              <Collapsible className="space-y-2">
                <CollapsibleTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="flex items-center justify-between w-full px-2 py-1 h-7"
                  >
                    <span className="flex items-center">
                      <Send size={14} className="mr-2" /> Last Message Sent
                      {lastWsSent && `(${formatTime(lastWsSent.time)})`}
                    </span>
                    <ChevronDown size={14} />
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <pre className="bg-muted p-2 rounded-md overflow-x-auto whitespace-pre-wrap text-[10px] max-h-40">
                    {lastWsSent
                      ? JSON.stringify(lastWsSent.data, null, 2)
                      : "No messages sent"}
                  </pre>
                </CollapsibleContent>
              </Collapsible>

              <Collapsible className="space-y-2">
                <CollapsibleTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="flex items-center justify-between w-full px-2 py-1 h-7"
                  >
                    <span className="flex items-center">
                      <Settings size={14} className="mr-2" /> Gamepad Input
                      Messages{" "}
                      {lastGamepadInputMessage &&
                        `(${formatTime(lastGamepadInputMessage.time)})`}
                    </span>
                    <ChevronDown size={14} />
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <pre className="bg-muted p-2 rounded-md overflow-x-auto whitespace-pre-wrap text-[10px] max-h-40">
                    {lastGamepadInputMessage
                      ? JSON.stringify(lastGamepadInputMessage.data, null, 2)
                      : "No gamepad input messages sent"}
                  </pre>
                </CollapsibleContent>
              </Collapsible>

              <Collapsible className="space-y-2">
                <CollapsibleTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="flex items-center justify-between w-full px-2 py-1 h-7"
                  >
                    <span className="flex items-center">
                      <Clock size={14} className="mr-2" /> Ping Messages
                      {lastPingMessage &&
                        `(${formatTime(lastPingMessage.time)})`}
                    </span>
                    <ChevronDown size={14} />
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <pre className="bg-muted p-2 rounded-md overflow-x-auto whitespace-pre-wrap text-[10px] max-h-40">
                    {lastPingMessage
                      ? JSON.stringify(lastPingMessage.data, null, 2)
                      : "No ping messages sent"}
                  </pre>
                </CollapsibleContent>
              </Collapsible>

              <Collapsible className="space-y-2">
                <CollapsibleTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="flex items-center justify-between w-full px-2 py-1 h-7"
                  >
                    <span className="flex items-center">
                      <Download size={14} className="mr-2" /> Last Message
                      Received
                      {lastWsReceived && `(${formatTime(lastWsReceived.time)})`}
                    </span>
                    <ChevronDown size={14} />
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <pre className="bg-muted p-2 rounded-md overflow-x-auto whitespace-pre-wrap text-[10px] max-h-40">
                    {lastWsReceived
                      ? JSON.stringify(lastWsReceived.data, null, 2)
                      : "No messages received"}
                  </pre>
                </CollapsibleContent>
              </Collapsible>

              <div className="space-y-2">
                <div className="font-medium">Test Tools</div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-xs h-7 px-2"
                    onClick={() =>
                      window.dispatchEvent(
                        new CustomEvent("debug:reconnect-ws")
                      )
                    }
                  >
                    Reconnect WS
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-xs h-7 px-2"
                    onClick={() =>
                      window.dispatchEvent(new CustomEvent("debug:send-ping"))
                    }
                  >
                    Send Test Ping
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-xs h-7 px-2"
                    onClick={() =>
                      window.dispatchEvent(
                        new CustomEvent("debug:clear-ws-logs")
                      )
                    }
                  >
                    Clear WS Logs
                  </Button>
                </div>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="gamepad">
            <div className="space-y-4">
              <Collapsible>
                <CollapsibleTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="flex items-center justify-between w-full px-2 py-1 h-7"
                  >
                    <span className="flex items-center">
                      <Settings size={14} className="mr-2" /> Pressed Inputs
                    </span>
                    <ChevronDown size={14} />
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <div className="p-2 bg-muted rounded-md">
                    {pressedInputsArray.length === 0 ? (
                      <div className="text-muted-foreground p-1">
                        No active inputs
                      </div>
                    ) : (
                      <div className="grid grid-cols-4 gap-1">
                        {pressedInputsArray.map((input, idx) => (
                          <div key={idx} className="p-1 rounded bg-primary/20">
                            {input}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </CollapsibleContent>
              </Collapsible>

              <Collapsible>
                <CollapsibleTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="flex items-center justify-between w-full px-2 py-1 h-7"
                  >
                    <span className="flex items-center">
                      <Settings size={14} className="mr-2" /> Axis Values
                    </span>
                    <ChevronDown size={14} />
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <div className="grid grid-cols-4 gap-1 p-2 bg-muted rounded-md">
                    {Object.entries(axisValues || {}).map(([index, value]) => (
                      <div key={index} className="p-1">
                        Axis {index}:{" "}
                        {typeof value === "number" ? value.toFixed(2) : "N/A"}
                      </div>
                    ))}
                    {Object.keys(axisValues || {}).length === 0 && (
                      <div className="text-muted-foreground col-span-4 p-1">
                        No axis data available
                      </div>
                    )}
                  </div>
                </CollapsibleContent>
              </Collapsible>

              <Collapsible>
                <CollapsibleTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="flex items-center justify-between w-full px-2 py-1 h-7"
                  >
                    <span className="flex items-center">
                      <Settings size={14} className="mr-2" /> Mappings
                    </span>
                    <ChevronDown size={14} />
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <pre className="bg-muted p-2 rounded-md overflow-x-auto whitespace-pre-wrap text-[10px] max-h-40">
                    {JSON.stringify(mappings, null, 2)}
                  </pre>
                </CollapsibleContent>
              </Collapsible>

              <Collapsible>
                <CollapsibleTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="flex items-center justify-between w-full px-2 py-1 h-7"
                  >
                    <span className="flex items-center">
                      <Settings size={14} className="mr-2" /> Gamepad Info
                    </span>
                    <ChevronDown size={14} />
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  {selectedGamepadId ? (
                    <div className="grid grid-cols-2 gap-1 p-2 bg-muted rounded-md text-[10px]">
                      {availableGamepads
                        .filter((g) => g.id === selectedGamepadId)
                        .map((gamepad) => (
                          <div
                            key={gamepad.id}
                            className="col-span-2 space-y-1"
                          >
                            <div className="font-medium">{gamepad.id}</div>
                            <div className="grid grid-cols-2 gap-x-2">
                              <div>
                                Connected: {gamepad.connected ? "Yes" : "No"}
                              </div>
                              <div>Timestamp: {gamepad.timestamp}</div>
                              <div>Buttons: {gamepad.buttons.length}</div>
                              <div>Axes: {gamepad.axes.length}</div>
                              <div>Mapping: {gamepad.mapping || "N/A"}</div>
                              <div>Index: {gamepad.index}</div>
                            </div>
                          </div>
                        ))}
                    </div>
                  ) : (
                    <div className="text-muted-foreground p-2 bg-muted rounded-md">
                      No gamepad selected
                    </div>
                  )}
                </CollapsibleContent>
              </Collapsible>
            </div>
          </TabsContent>

          <TabsContent value="errors">
            <div className="space-y-2">
              {errorLogs.length === 0 ? (
                <div className="text-center py-4 text-muted-foreground">
                  No errors logged
                </div>
              ) : (
                errorLogs.slice(0, 10).map((log, i) => (
                  <Collapsible key={i}>
                    <CollapsibleTrigger asChild>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="flex items-center justify-between w-full px-2 py-1 h-7 text-destructive"
                      >
                        <span className="flex items-center">
                          <AlertCircle size={14} className="mr-2" />
                          <span className="text-xs">
                            {formatTime(log.time)}: {log.message}
                          </span>
                        </span>
                        <ChevronDown size={14} />
                      </Button>
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                      <pre className="bg-muted p-2 rounded-md overflow-x-auto whitespace-pre-wrap text-[10px]">
                        {log.details
                          ? JSON.stringify(log.details, null, 2)
                          : "No additional details"}
                      </pre>
                    </CollapsibleContent>
                  </Collapsible>
                ))
              )}

              <Button
                variant="outline"
                size="sm"
                className="text-xs h-7 px-2"
                onClick={() => {
                  errorLogs = [];
                  // Force re-render
                  window.dispatchEvent(new CustomEvent("debug:clear-errors"));
                }}
              >
                Clear Errors
              </Button>
            </div>
          </TabsContent>

          <TabsContent value="perf">
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-4">
                <div className="bg-muted p-2 rounded-md text-center">
                  <div className="text-muted-foreground text-[10px]">FPS</div>
                  <div className="text-xl font-bold">
                    {performanceStats.fps}
                  </div>
                </div>
                <div className="bg-muted p-2 rounded-md text-center">
                  <div className="text-muted-foreground text-[10px]">
                    Frame Time
                  </div>
                  <div className="text-xl font-bold">
                    {performanceStats.lastFrameTime}ms
                  </div>
                </div>
                <div className="bg-muted p-2 rounded-md text-center">
                  <div className="text-muted-foreground text-[10px]">
                    Memory
                  </div>
                  <div className="text-xl font-bold">
                    {/* Memory usage if available */}
                    {(
                      window.performance as Performance & {
                        memory?: { usedJSHeapSize: number };
                      }
                    )?.memory
                      ? `${Math.round(
                          (
                            window.performance as Performance & {
                              memory?: { usedJSHeapSize: number };
                            }
                          ).memory!.usedJSHeapSize / 1048576
                        )}MB`
                      : "N/A"}
                  </div>
                </div>
              </div>

              <div>
                <div className="font-medium mb-1">
                  Frame Times (last 60 frames)
                </div>
                <div className="bg-muted h-20 w-full rounded-md p-1 flex items-end">
                  {performanceStats.updateTimes.map((time, i) => (
                    <div
                      key={i}
                      className="w-full h-full"
                      style={{
                        height: `${Math.min(100, (time / 33) * 100)}%`,
                        backgroundColor:
                          time > 16 ? "var(--destructive)" : "var(--primary)",
                        opacity: 0.7,
                        width: `${
                          100 /
                          Math.max(60, performanceStats.updateTimes.length)
                        }%`,
                        marginRight: "1px",
                      }}
                      title={`${time.toFixed(1)}ms`}
                    />
                  ))}
                </div>
              </div>
            </div>
          </TabsContent>
        </Tabs>

        <div className="mt-4 pt-4 border-t text-muted-foreground flex justify-between">
          <div className="flex items-center">
            <Clock size={12} className="mr-1" />
            <span>{now.toISOString()}</span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2"
            onClick={() => window.location.reload()}
          >
            Reload Page
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
