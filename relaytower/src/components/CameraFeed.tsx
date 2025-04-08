"use client";
import { useState, useEffect, useRef, useCallback, memo } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { RefreshCw, Maximize, X, AlertCircle, ChevronRight, Eye, EyeOff } from "lucide-react";
import { Button } from "./ui/button";
import { useWebSocket } from "@/contexts/WebSocketContext";
import MiniSensorOverlay from "./MiniSensorOverlay";

// Memoized freeze notification component to prevent unnecessary re-renders
const FreezeNotification = memo(({
  isFullscreen,
  onRestart,
  onDismiss
}: {
  isFullscreen: boolean;
  onRestart: () => void;
  onDismiss: (e?: React.MouseEvent) => void;
}) => {
  const [isHovered, setIsHovered] = useState(false);

  // For non-fullscreen mode, just show a button in the header
  if (!isFullscreen) {
    return (
      <Button
        variant="destructive"
        size="sm"
        onClick={onRestart}
        className="h-8 px-2 flex items-center"
      >
        <AlertCircle className="h-4 w-4 mr-1" />
        <span>Restart Camera</span>
        <X
          className="h-3.5 w-3.5 ml-2 opacity-70 hover:opacity-100"
          onClick={(e) => {
            e.stopPropagation();
            onDismiss(e);
          }}
        />
      </Button>
    );
  }

  // For fullscreen mode, show a notification that expands on hover
  const baseClasses = "absolute top-6 left-6 z-50 rounded-md shadow-lg transition-all duration-300";

  if (isHovered) {
    // Expanded notification
    return (
      <div
        className={`${baseClasses} bg-destructive text-white p-4 max-w-md animate-in fade-in-0 duration-150`}
        onMouseLeave={() => setIsHovered(false)}
      >
        <div className="flex items-start gap-3">
          <div className="shrink-0">
            <AlertCircle className="h-5 w-5" />
          </div>
          <div className="flex-1">
            <h3 className="font-medium mb-1">Camera Feed Frozen</h3>
            <p className="text-sm opacity-90 mb-3">
              The camera feed appears to be frozen. Would you like to restart it?
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={onRestart}
                className="text-black border-white hover:bg-white/20"
              >
                Restart Camera
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={onDismiss}
                className="text-white hover:bg-white/20"
              >
                Dismiss
              </Button>
            </div>
          </div>
          <button
            onClick={onDismiss}
            className="shrink-0 rounded-full p-1 transition-colors hover:bg-white/20"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>
    );
  } else {
    // Compact notification
    return (
      <div
        className={`${baseClasses} bg-destructive text-white py-2 px-3 flex items-center cursor-pointer`}
        onMouseEnter={() => setIsHovered(true)}
      >
        <AlertCircle className="h-4 w-4 mr-2" />
        <span className="mr-2">Camera frozen</span>
        <ChevronRight className="h-4 w-4 opacity-70" />
      </div>
    );
  }
});

// Ensure the component has a display name for debugging
FreezeNotification.displayName = "FreezeNotification";

export default function CameraFeed() {
  // Use window.location.hostname to get the current server hostname dynamically
  const [streamUrl, setStreamUrl] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [key, setKey] = useState(Date.now()); // Used to force refresh the stream
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showControls, setShowControls] = useState(false);
  const [aspectRatio, setAspectRatio] = useState("4/3"); // Default aspect ratio
  const [showSensorOverlay, setShowSensorOverlay] = useState(true); // State to toggle sensor overlay

  // Use refs for values that shouldn't trigger re-renders when they change
  const isFrozenRef = useRef(false);
  const userDismissedRef = useRef(false);
  const prevFrozenStateRef = useRef(false);

  // State to force notification rendering - will only change when truly needed
  const [notificationKey, setNotificationKey] = useState(0);

  const { cameraStatus, restartCameraFeed } = useWebSocket();

  const controlsTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const fullscreenContainerRef = useRef<HTMLDivElement>(null);

  // Check for custom camera URL in localStorage
  useEffect(() => {
    const customUrl = localStorage.getItem("debug_camera_url");
    if (customUrl && customUrl.trim() !== "") {
      setStreamUrl(customUrl);
    } else {
      // Use default URL
      const hostname = window.location.hostname;
      setStreamUrl(`http://${hostname}:9000/mjpg`);
    }
  }, []);

  // Monitor camera status for freezes - with a stable comparison approach
  useEffect(() => {
    if (!cameraStatus) return;

    const isCameraCurrentlyFrozen = cameraStatus.state === "FROZEN";
    const wasFrozenBefore = prevFrozenStateRef.current;

    // Only take action if the frozen state actually changed
    if (isCameraCurrentlyFrozen !== wasFrozenBefore) {
      prevFrozenStateRef.current = isCameraCurrentlyFrozen;
      isFrozenRef.current = isCameraCurrentlyFrozen;

      if (isCameraCurrentlyFrozen) {
        // Camera just became frozen
        userDismissedRef.current = false;
        // Force a notification update by changing the key
        setNotificationKey(prev => prev + 1);
      } else {
        // Camera is no longer frozen
        userDismissedRef.current = false;
        // Force a notification update by changing the key
        setNotificationKey(prev => prev + 1);
      }
    }

    // Update aspect ratio based on camera resolution
    if (cameraStatus.settings && cameraStatus.settings.resolution) {
      const resolution = cameraStatus.settings.resolution;
      const [width, height] = resolution.split("x").map(Number);
      if (width && height) {
        setAspectRatio(`${width}/${height}`);
      }
    }
  }, [cameraStatus]);

  // Handle escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isFullscreen) {
        setIsFullscreen(false);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isFullscreen]);

  // Handle fullscreen change events
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };

    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () =>
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  // Handle mouse movement to show/hide controls in fullscreen mode
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

    // Initial timeout
    handleMouseMove();

    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      if (controlsTimeoutRef.current) {
        clearTimeout(controlsTimeoutRef.current);
      }
    };
  }, [isFullscreen]);

  const refreshStream = useCallback(() => {
    setIsLoading(true);
    setError(null);
    setKey(Date.now()); // Change key to force img reload
  }, []);

  const handleImageLoad = useCallback(() => {
    setIsLoading(false);
    setError(null);
  }, []);

  const handleImageError = useCallback(() => {
    setIsLoading(false);
    setError(
      "Unable to connect to camera stream. Check if the camera is online."
    );
  }, []);

  const toggleFullscreen = useCallback(() => {
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
  }, [isFullscreen]);

  const restartCamera = useCallback(() => {
    restartCameraFeed();
  }, [restartCameraFeed]);

  const dismissCurrentFreezeNotification = useCallback((e?: React.MouseEvent) => {
    if (e) {
      e.stopPropagation();
    }
    userDismissedRef.current = true;
    // Force re-render of notification state
    setNotificationKey(prev => prev + 1);
  }, []);

  // Determine if we should show the notification
  const shouldShowNotification = isFrozenRef.current && !userDismissedRef.current;

  if (isFullscreen) {
    return (
      <div
        ref={fullscreenContainerRef}
        className="fixed inset-0 z-50 bg-black m-0"
      >
        {/* Blurred background */}
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

        {/* Main video feed */}
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

        {/* Loading indicator */}
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/30 z-20">
            <div className="animate-spin h-12 w-12 border-4 border-primary border-t-transparent rounded-full"></div>
          </div>
        )}

        {/* Error message */}
        {error && (
          <div className="absolute inset-0 flex flex-col items-center justify-center p-4 z-30 bg-black/70">
            <p className="mb-4 text-center max-w-md text-white">{error}</p>
            <Button onClick={refreshStream}>
              <RefreshCw className="h-4 w-4 mr-2" />
              Try Again
            </Button>
          </div>
        )}

        {/* Freeze notification - only rendered when needed, with a stable key to prevent flickering */}
        {shouldShowNotification && (
          <FreezeNotification
            key={`fullscreen-notification-${notificationKey}`}
            isFullscreen={true}
            onRestart={restartCamera}
            onDismiss={dismissCurrentFreezeNotification}
          />
        )}

        {/* Exit fullscreen button - visible only on mouse movement */}
        <div
          className={`absolute top-6 right-6 transition-opacity duration-300 z-50 ${showControls ? "opacity-100" : "opacity-0 pointer-events-none"
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

        {/* Sensor overlay toggle button - visible only on mouse movement */}
        <div
          className={`absolute top-6 right-20 transition-opacity duration-300 z-50 ${showControls ? "opacity-100" : "opacity-0 pointer-events-none"
            }`}
        >
          <Button
            variant="secondary"
            size="icon"
            onClick={() => setShowSensorOverlay(!showSensorOverlay)}
            className="h-10 w-10 rounded-full bg-white/50 hover:bg-white/70 backdrop-blur-sm"
          >
            {showSensorOverlay ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
          </Button>
        </div>

        {/* Mini Sensor Overlay - only visible in fullscreen mode if enabled */}
        {showSensorOverlay && <MiniSensorOverlay position="bottom-right" />}
      </div>
    );
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <div className="flex justify-between items-center">
          <CardTitle className="text-lg">Camera Feed</CardTitle>
          <div className="flex gap-2">
            {/* Freeze notification for card view - only rendered when needed */}
            {shouldShowNotification && (
              <FreezeNotification
                key={`card-notification-${notificationKey}`}
                isFullscreen={false}
                onRestart={restartCamera}
                onDismiss={dismissCurrentFreezeNotification}
              />
            )}
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


        <div className="relative rounded-md overflow-hidden aspect-[16/9]">
          {isLoading && (
            <div className="absolute inset-0 flex items-center justify-center bg-background z-20">
              <div className="animate-spin h-8 w-8 border-4 border-primary border-t-transparent rounded-full"></div>
            </div>
          )}
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

          {/* Main camera feed with dynamic aspect ratio */}
          <div className="absolute inset-0 flex items-center justify-center z-10">
            <div className="relative h-full" style={{ aspectRatio }}>
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
