"use client";
import { useState, useEffect, useRef } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { RefreshCw, Maximize, X, AlertTriangle } from "lucide-react";
import { Button } from "./ui/button";

export default function CameraFeed() {
  const [streamUrl, setStreamUrl] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [key, setKey] = useState(Date.now());
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showControls, setShowControls] = useState(false);

  const fullscreenContainerRef = useRef<HTMLDivElement>(null);
  const controlsTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Camera warnings
  const [cameraWarning, setCameraWarning] = useState<string | null>(null);
  const [showWarning, setShowWarning] = useState(false);
  const warningTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    const customUrl = localStorage.getItem("debug_camera_url");
    if (customUrl && customUrl.trim() !== "") {
      setStreamUrl(customUrl);
    } else {
      const hostname = window.location.hostname;
      setStreamUrl(`http://${hostname}:9000/mjpg`);
    }
  }, []);

  // Listen for camera status
  useEffect(() => {
    const handleCameraStatus = (e: CustomEvent) => {
      const { status, message } = e.detail;
      if (status === "error" || status === "restarted") {
        setCameraWarning(message);
        setShowWarning(true);
        if (warningTimeoutRef.current) {
          clearTimeout(warningTimeoutRef.current);
        }
        warningTimeoutRef.current = setTimeout(() => {
          setShowWarning(false);
        }, 5000);
        if (status === "restarted") {
          refreshStream();
        }
      }
    };
    window.addEventListener(
      "debug:camera-status",
      handleCameraStatus as EventListener
    );
    return () => {
      window.removeEventListener(
        "debug:camera-status",
        handleCameraStatus as EventListener
      );
      if (warningTimeoutRef.current) {
        clearTimeout(warningTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isFullscreen) {
        setIsFullscreen(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isFullscreen]);

  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => {
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
    };
  }, []);

  useEffect(() => {
    if (!isFullscreen) return;
    const handleMouseMove = () => {
      setShowControls(true);
      if (controlsTimeoutRef.current) {
        clearTimeout(controlsTimeoutRef.current);
      }
      controlsTimeoutRef.current = setTimeout(() => {
        setShowControls(false);
      }, 3000);
    };
    window.addEventListener("mousemove", handleMouseMove);
    handleMouseMove();
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      if (controlsTimeoutRef.current) {
        clearTimeout(controlsTimeoutRef.current);
      }
    };
  }, [isFullscreen]);

  const refreshStream = () => {
    setIsLoading(true);
    setError(null);
    setKey(Date.now());
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

  const toggleFullscreen = () => {
    if (!isFullscreen) {
      if (fullscreenContainerRef.current && document.fullscreenEnabled) {
        fullscreenContainerRef.current.requestFullscreen().catch((err) => {
          console.error(
            `Error attempting to enable fullscreen: ${err.message}`
          );
        });
      }
    } else {
      if (document.fullscreenElement) {
        document.exitFullscreen().catch((err) => {
          console.error(`Error attempting to exit fullscreen: ${err.message}`);
        });
      }
    }
    setIsFullscreen(!isFullscreen);
  };

  const WarningToast = () => {
    if (!showWarning || !cameraWarning) return null;
    return (
      <div className="absolute top-4 right-4 z-50 bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200 px-4 py-2 rounded-md shadow-lg flex items-center gap-2 max-w-xs animate-in slide-in-from-right">
        <AlertTriangle className="h-4 w-4 flex-shrink-0" />
        <span className="text-xs">{cameraWarning}</span>
        <Button
          onClick={() => setShowWarning(false)}
          className="ml-2 text-yellow-800 dark:text-yellow-200 hover:text-yellow-900 dark:hover:text-yellow-100"
        >
          <X className="h-3 w-3" />
        </Button>
      </div>
    );
  };

  if (isFullscreen) {
    return (
      <div ref={fullscreenContainerRef} className="fixed inset-0 z-50 bg-black">
        <WarningToast />
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
        </div>
        <div className="absolute inset-0 flex items-center justify-center z-10">
          <img
            key={key}
            src={streamUrl}
            alt="Camera Feed"
            className="h-screen"
            onLoad={handleImageLoad}
            onError={handleImageError}
          />
        </div>
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/30 z-20">
            <div className="animate-spin h-12 w-12 border-4 border-primary border-t-transparent rounded-full"></div>
          </div>
        )}
        {error && (
          <div className="absolute inset-0 flex flex-col items-center justify-center p-4 z-30 bg-black/70">
            <p className="mb-4 text-center max-w-md text-white">{error}</p>
            <Button onClick={refreshStream}>
              <RefreshCw className="h-4 w-4 mr-2" />
              Try Again
            </Button>
          </div>
        )}
        <div
          className={`absolute top-6 right-6 transition-opacity duration-300 z-50 ${
            showControls ? "opacity-100" : "opacity-0 pointer-events-none"
          }`}
        >
          <Button
            variant="secondary"
            size="icon"
            onClick={toggleFullscreen}
            className="h-10 w-10 rounded-full bg-white/50 hover:bg-white/70 backdrop-blur-sm"
          >
            <X className="h-5 w-5" />
          </Button>
        </div>
      </div>
    );
  }

  return (
    <Card className="overflow-hidden relative">
      <WarningToast />
      <CardHeader>
        <div className="flex justify-between items-center">
          <CardTitle className="text-lg">Camera Feed</CardTitle>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={toggleFullscreen}
              className="h-8 px-2"
            >
              <Maximize className="h-4 w-4 mr-1" />
              Fullscreen
            </Button>
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
        </div>
      </CardHeader>
      <CardContent className="relative">
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-background z-20">
            <div className="animate-spin h-8 w-8 border-4 border-primary border-t-transparent rounded-full"></div>
          </div>
        )}
        <div className="relative rounded-md overflow-hidden aspect-[16/9]">
          {error && (
            <div className="absolute inset-0 flex flex-col items-center justify-center p-4 z-30 rounded-md bg-background">
              <p className="mb-4 text-center max-w-md">{error}</p>
              <Button onClick={refreshStream}>
                <RefreshCw className="h-4 w-4 mr-2" />
                Try Again
              </Button>
            </div>
          )}
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
          <div className="absolute inset-0 flex items-center justify-center z-10">
            <div className="relative aspect-[4/3] h-full">
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
