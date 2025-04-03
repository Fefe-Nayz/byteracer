"use client";
import { useEffect, useRef, useState } from "react";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select, SelectTrigger,SelectValue, SelectContent, SelectItem
 } from "@/components/ui/select";

interface LogViewerProps {
  maxHeight?: string;
  className?: string;
}

export default function LogViewer({ maxHeight = "400px", className = "" }: LogViewerProps) {
  const { logs, clearLogs } = useWebSocket();
  const logEndRef = useRef<HTMLDivElement>(null);
  const [filterLevel, setFilterLevel] = useState<string | null>(null);

  // Filter logs based on level
  const filteredLogs = filterLevel
    ? logs.filter(log => log.level === filterLevel)
    : logs;

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [filteredLogs]);

  // Get unique log levels for filter
  const logLevels = Array.from(new Set(logs.map(log => log.level)));

  // Format timestamp
  const formatTimestamp = (timestamp: number) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString();
  };

  // Get color class for log level
  const getLogLevelColor = (level: string) => {
    switch (level.toUpperCase()) {
      case "ERROR":
      case "CRITICAL":
        return "text-red-500 font-semibold";
      case "WARNING":
        return "text-amber-500";
      case "INFO":
        return "text-blue-500";
      case "DEBUG":
        return "text-gray-500";
      default:
        return "text-gray-700";
    }
  };

  return (
    <Card className={`p-4 ${className}`}>
      <div className="flex justify-between items-center mb-3">
        <h3 className="text-lg font-medium">Robot Logs</h3>
        <div className="flex gap-2">
          
          <Select value={filterLevel || ""} onValueChange={(value) => setFilterLevel(value || null)}>
            <SelectTrigger className="w-[140px] h-8 text-sm">
              <SelectValue placeholder="All Levels" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="All">All Levels</SelectItem>
              {logLevels.map((level) => (
                <SelectItem key={level} value={level}>
                  {level}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          
          <Button 
            onClick={clearLogs} 
            variant="destructive" 
            size="sm"
          >
            Clear
          </Button>
        </div>
      </div>

      <div 
        className="font-mono text-sm bg-gray-100 p-3 rounded overflow-y-auto whitespace-pre-wrap"
        style={{ maxHeight }}
      >
        {filteredLogs.length === 0 ? (
          <div className="text-gray-500 italic">No logs to display</div>
        ) : (
          filteredLogs.map((log, index) => (
            <div key={index} className="mb-1">
              <span className="text-gray-600">{formatTimestamp(log.timestamp)}</span>
              {" "}
              <span className={getLogLevelColor(log.level)}>[{log.level}]</span>
              {" "}
              <span>{log.message}</span>
            </div>
          ))
        )}
        <div ref={logEndRef} />
      </div>
    </Card>
  );
}