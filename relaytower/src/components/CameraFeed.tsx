"use client";
import { useState, useEffect } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { RefreshCw } from "lucide-react";
import { Button } from "./ui/button";

export default function CameraFeed() {
  // Use window.location.hostname to get the current server hostname dynamically
  const [streamUrl, setStreamUrl] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [key, setKey] = useState(Date.now()); // Used to force refresh the stream

  // Set URL when component mounts (and whenever hostname might change)
  useEffect(() => {
    // This will work regardless of whether it's an IP address or hostname
    const hostname = window.location.hostname;
    setStreamUrl(`http://${hostname}:9000/mjpg`);
  }, []);

  const refreshStream = () => {
    setIsLoading(true);
    setError(null);
    setKey(Date.now()); // Change key to force img reload
  };

  const handleImageLoad = () => {
    setIsLoading(false);
    setError(null);
  };

  const handleImageError = () => {
    setIsLoading(false);
    setError(
      "Unable to connect to camera stream. Check if the camera is online."
    );
  };

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <div className="flex justify-between items-center">
          <CardTitle className="text-lg">Camera Feed</CardTitle>
          <Button
            variant="outline"
            size="sm"
            onClick={refreshStream}
            className="h-8 px-2"
          >
            <RefreshCw className="h-4 w-4 mr-1" />
            Refresh
          </Button>
        </div>
      </CardHeader>
      <CardContent className="relative">
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-background z-20">
            <div className="animate-spin h-8 w-8 border-4 border-primary border-t-transparent rounded-full"></div>
          </div>
        )}

        <div
          className="relative rounded-md overflow-hidden"
          style={{ aspectRatio: "16/9" }}
        >
          {/* Error state - positioned over entire feed */}
          {error && (
            <div className="absolute inset-0 flex flex-col items-center justify-center p-4 z-30 rounded-md bg-background">
              <p className="mb-4 text-center max-w-md">{error}</p>
              <Button onClick={refreshStream}>
                <RefreshCw className="h-4 w-4 mr-2" />
                Try Again
              </Button>
            </div>
          )}

          {/* Blurred background version (full width) */}
          <div className="absolute inset-0 overflow-hidden">
            <img
              key={`bg-${key}`}
              src={streamUrl}
              alt=""
              className="w-full h-full object-cover scale-110"
              style={{
                filter: "blur(15px)",
                opacity: 0.7,
                transform: "scale(1.1)",
              }}
            />
            <div className="absolute inset-0"></div>
          </div>

          {/* Centered 4:3 aspect ratio version */}
          <div className="absolute inset-0 flex items-center justify-center z-10">
            <div
              className="relative"
              style={{ aspectRatio: "4/3", height: "100%" }}
            >
              <img
                key={key}
                src={streamUrl}
                alt="Camera Feed"
                className="h-full w-auto object-contain"
                style={{ maxHeight: "100%", maxWidth: "100%" }}
                onLoad={handleImageLoad}
                onError={handleImageError}
              />
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
