import { useState, useEffect } from "react";
import { useWebSocket } from "@/contexts/WebSocketContext";
import { Card } from "./ui/card";
import { Input } from "./ui/input";
import { Button } from "./ui/button";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import { Wifi, Globe, Loader2, PlusCircle, Trash2, WifiOff } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { Badge } from "./ui/badge";

type NetworkMode = "wifi" | "ap";
type WifiNetwork = { ssid: string; password: string };

// Define interface for network status
interface NetworkStatus {
  ap_mode_active: boolean;
  current_ip: string;
  current_connection?: {
    ssid: string;
    name: string;
    ip?: string;
  };
  ap_ssid?: string;
  internet_connected: boolean;
}

interface SavedNetwork {
  ssid: string;
  id: string;
}

export default function NetworkSettings() {
  const { toast } = useToast();
  const { status, scanNetworks, updateNetwork, requestSettings } = useWebSocket();
  
  // Local state for form values
  const [mode, setMode] = useState<NetworkMode>("wifi");
  const [apName, setApName] = useState("");
  const [apPassword, setApPassword] = useState("");
  const [knownNetworks, setKnownNetworks] = useState<WifiNetwork[]>([]);
  const [newSsid, setNewSsid] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [availableNetworks, setAvailableNetworks] = useState<string[]>([]);
  const [isScanning, setIsScanning] = useState(false);
  const [networkStatus, setNetworkStatus] = useState<NetworkStatus>({
    ap_mode_active: false,
    current_ip: "",
    internet_connected: false
  });

  
  // Request settings when component mounts or reconnects
  useEffect(() => {
    if (status === "connected") {
      requestSettings();
      scanNetworks(); // Also request network scan on initial load
    }
  }, [status, requestSettings, scanNetworks]);
  
  // Listen for network scan results
  useEffect(() => {
    const handleNetworkList = (event: CustomEvent) => {
      if (event.detail) {
        // Update available networks
        if (Array.isArray(event.detail.networks)) {
          setAvailableNetworks(event.detail.networks);
          setIsScanning(false);
          
          toast({
            title: "Network scan complete",
            description: `Found ${event.detail.networks.length} networks`,
            duration: 3000,
          });
        }
        
        // Update saved networks
        if (Array.isArray(event.detail.saved_networks)) {
          // Convert saved network format to our local format
          const savedNetworks = event.detail.saved_networks.map((network: SavedNetwork) => ({
            ssid: network.ssid,
            password: "********" // Password is not provided from server for security
          }));
          
          setKnownNetworks(savedNetworks);
        }
        
        // Update network status
        if (event.detail.status) {
          setNetworkStatus(event.detail.status);
          
          // Update mode based on active mode from status
          if (event.detail.status.ap_mode_active) {
            setMode("ap");
          } else {
            setMode("wifi");
          }
        }
      }
    };
    
    // Add event listener
    window.addEventListener(
      "debug:network-list",
      handleNetworkList as EventListener
    );
    
    // Clean up
    return () => {
      window.removeEventListener(
        "debug:network-list",
        handleNetworkList as EventListener
      );
    };
  }, [toast, setIsScanning, setAvailableNetworks, setKnownNetworks, setNetworkStatus, setMode]);
  
  // Start network scan
  const handleScanNetworks = () => {
    setIsScanning(true);
    scanNetworks();
    
    // Set a timeout to clear the scanning state in case no response
    setTimeout(() => {
      if (isScanning) {
        setIsScanning(false);
        toast({
          title: "Network scan timeout",
          description: "No response from the robot",
          variant: "destructive",
        });
      }
    }, 15000); // 15 seconds timeout
  };
  
  // Add new WiFi network
  const handleAddNetwork = () => {
    if (!newSsid.trim() || !newPassword.trim()) {
      toast({
        title: "Error",
        description: "SSID and password are required",
        variant: "destructive",
      });
      return;
    }
    
    // Send update to robot
    updateNetwork("add_network", { ssid: newSsid, password: newPassword });
    
    // Reset form
    setNewSsid("");
    setNewPassword("");
    
    toast({
      title: "Network added",
      description: `Added network: ${newSsid}`,
      duration: 3000,
    });
  };
  
  // Remove WiFi network
  const handleRemoveNetwork = (ssid: string) => {
    // Send update to robot
    updateNetwork("remove_network", { ssid });
    
    toast({
      title: "Network removed",
      description: `Removed network: ${ssid}`,
      duration: 3000,
    });
  };
  
  // Save AP settings
  const handleSaveAP = () => {
    if (!apName.trim() || !apPassword.trim() || apPassword.length < 8) {
      toast({
        title: "Error",
        description: "AP name and password (min 8 chars) are required",
        variant: "destructive",
      });
      return;
    }
    
    // Update AP settings
    updateNetwork("update_ap_settings", { 
      ap_name: apName, 
      ap_password: apPassword 
    });
    
    toast({
      title: "AP settings saved",
      description: "Access Point settings updated",
      duration: 3000,
    });
  };
  
  // Change network mode
  const handleModeChange = (newMode: NetworkMode) => {
    if (newMode === mode) return; // No change
    
    setMode(newMode);
    
    // Execute the actual mode switch
    if (newMode === "ap") {
      updateNetwork("create_ap", {});
    } else {
      updateNetwork("connect_wifi_mode", {});
    }
    
    toast({
      title: "Network mode changing",
      description: `Switching to ${newMode === "wifi" ? "WiFi" : "Access Point"} mode...`,
      duration: 3000,
    });
  };
  
  // Connect to a WiFi network
  const handleConnectToWifi = () => {
    if (!newSsid.trim() || !newPassword.trim()) {
      toast({
        title: "Error",
        description: "SSID and password are required to connect",
        variant: "destructive",
      });
      return;
    }
    
    updateNetwork("connect_wifi", { 
      ssid: newSsid, 
      password: newPassword 
    });
    
    toast({
      title: "Connecting to WiFi",
      description: `Connecting to ${newSsid}...`,
      duration: 3000,
    });
  };
  
  // Use a network from the scan results
  const handleUseNetwork = (ssid: string) => {
    setNewSsid(ssid);
  };
  
  // If not connected, show placeholder
  if (status !== "connected") {
    return (
      <Card className="p-4">
        <h3 className="font-bold mb-3">Network Settings</h3>
        <div className="text-sm text-gray-500 italic">
          {status === "connecting" 
            ? "Connecting to robot..." 
            : "Connect to robot to view network settings"}
        </div>
      </Card>
    );
  }
  
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center space-x-2">
          <Globe className="h-5 w-5" />
          <h3 className="font-bold">Network Settings</h3>
        </div>
        
        {/* Connection Status */}
        <div className="flex items-center space-x-2">
          {networkStatus.internet_connected ? (
            <Badge variant="outline" className="bg-green-50 text-green-600 border-green-200">
              <Wifi className="h-3 w-3 mr-1" />
              Internet Connected
            </Badge>
          ) : (
            <Badge variant="outline" className="bg-yellow-50 text-yellow-600 border-yellow-200">
              <WifiOff className="h-3 w-3 mr-1" />
              No Internet
            </Badge>
          )}
          
          {networkStatus.current_ip && (
            <Badge variant="outline" className="text-xs">
              IP: {networkStatus.current_ip}
            </Badge>
          )}
        </div>
      </div>
      
      {/* Current Connection Info */}
      <div className="mb-4 p-2 border rounded-md bg-muted/30">
        <div className="text-sm font-medium mb-1">Current Connection:</div>
        {networkStatus.ap_mode_active ? (
          <div className="flex items-center space-x-2">
            <Globe className="h-4 w-4 text-primary" />
            <span>Access Point Mode: {networkStatus.ap_ssid || apName || "ByteRacer_AP"}</span>
          </div>
        ) : networkStatus.current_connection ? (
          <div className="flex items-center space-x-2">
            <Wifi className="h-4 w-4 text-primary" />
            <span>Connected to: {networkStatus.current_connection.ssid}</span>
          </div>
        ) : (
          <div className="text-sm text-gray-500 italic">
            Not connected to any network
          </div>
        )}
      </div>
      
      <div className="mb-4">
        <div className="flex items-center space-x-4">
          <div
            className={`flex items-center space-x-2 p-2 rounded cursor-pointer ${
              mode === "wifi" ? "bg-primary/10" : ""
            }`}
            onClick={() => handleModeChange("wifi")}
          >
            <Wifi className={`h-4 w-4 ${mode === "wifi" ? "text-primary" : ""}`} />
            <span className={`text-sm ${mode === "wifi" ? "font-medium" : ""}`}>WiFi Client</span>
          </div>
          
          <div
            className={`flex items-center space-x-2 p-2 rounded cursor-pointer ${
              mode === "ap" ? "bg-primary/10" : ""
            }`}
            onClick={() => handleModeChange("ap")}
          >
            <Globe className={`h-4 w-4 ${mode === "ap" ? "text-primary" : ""}`} />
            <span className={`text-sm ${mode === "ap" ? "font-medium" : ""}`}>Access Point</span>
          </div>
        </div>
      </div>
      
      <Tabs defaultValue={mode} value={mode} className="w-full">
        <TabsContent value="wifi" className="mt-0">
          <div className="space-y-4">
            <div>
              <h4 className="text-sm font-medium mb-2">Known Networks</h4>
              
              {knownNetworks.length === 0 ? (
                <div className="text-sm text-gray-500 italic p-2">
                  No saved networks. Add a network below.
                </div>
              ) : (
                <div className="space-y-2 max-h-40 overflow-y-auto p-2 border rounded-md">
                  {knownNetworks.map((network) => (
                    <div key={network.ssid} className="flex justify-between items-center p-2 bg-muted/50 rounded">
                      <div className="flex items-center space-x-2">
                        <Wifi className="h-4 w-4" />
                        <span className="text-sm font-medium">{network.ssid}</span>
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleRemoveNetwork(network.ssid)}
                      >
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>
            
            <div>
              <h4 className="text-sm font-medium mb-2">Connect to WiFi</h4>
              <div className="space-y-2">
                <Input
                  value={newSsid}
                  onChange={(e) => setNewSsid(e.target.value)}
                  placeholder="WiFi SSID"
                />
                <Input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="WiFi Password"
                />
                <div className="flex space-x-2">
                  <Button
                    onClick={handleConnectToWifi}
                    disabled={!newSsid.trim() || !newPassword.trim()}
                    className="flex-1"
                    variant="secondary"
                  >
                    <Wifi className="h-4 w-4 mr-2" />
                    Connect
                  </Button>
                  <Button
                    onClick={handleAddNetwork}
                    disabled={!newSsid.trim() || !newPassword.trim()}
                    className="flex-1"
                  >
                    <PlusCircle className="h-4 w-4 mr-2" />
                    Save Network
                  </Button>
                </div>
              </div>
            </div>
            
            <div>
              <div className="flex justify-between items-center mb-2">
                <h4 className="text-sm font-medium">Available Networks</h4>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleScanNetworks}
                  disabled={isScanning}
                >
                  {isScanning ? (
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  ) : (
                    <Wifi className="h-4 w-4 mr-2" />
                  )}
                  {isScanning ? "Scanning..." : "Scan"}
                </Button>
              </div>
              
              <div className="max-h-40 overflow-y-auto border rounded-md p-1">
                {isScanning ? (
                  <div className="p-4 text-center text-sm text-gray-500">
                    <Loader2 className="h-5 w-5 animate-spin mx-auto mb-2" />
                    Scanning for networks...
                  </div>
                ) : availableNetworks.length > 0 ? (
                  <div className="space-y-1">
                    {availableNetworks.map((ssid) => {
                      // Check if this network is saved
                      const isSaved = knownNetworks.some(n => n.ssid === ssid);
                      const isConnected = networkStatus.current_connection?.ssid === ssid;
                      
                      return (
                        <div
                          key={ssid}
                          className={`flex justify-between items-center p-2 hover:bg-muted/50 rounded cursor-pointer ${
                            isConnected ? "bg-green-100 dark:bg-green-900/30" : ""
                          }`}
                          onClick={() => handleUseNetwork(ssid)}
                        >
                          <div className="flex items-center space-x-2">
                            <Wifi className={`h-4 w-4 ${isConnected ? "text-green-500" : ""}`} />
                            <span className="text-sm">{ssid}</span>
                            {isSaved && <Badge variant="outline" className="text-xs">Saved</Badge>}
                            {isConnected && <Badge variant="outline" className="bg-green-100 text-green-600 border-green-200 dark:bg-green-900/30 dark:text-green-400 dark:border-green-800 text-xs">Connected</Badge>}
                          </div>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleUseNetwork(ssid);
                            }}
                          >
                            Use
                          </Button>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="p-4 text-center text-sm text-gray-500">
                    No networks found. Click Scan to search for networks.
                  </div>
                )}
              </div>
            </div>
          </div>
        </TabsContent>
        
        <TabsContent value="ap" className="mt-0">
          <div className="space-y-4">
            <div>
              <h4 className="text-sm font-medium mb-2">Access Point Settings</h4>
              <div className="space-y-2">
                <Input
                  value={apName}
                  onChange={(e) => setApName(e.target.value)}
                  placeholder="Access Point Name"
                />
                <Input
                  type="password"
                  value={apPassword}
                  onChange={(e) => setApPassword(e.target.value)}
                  placeholder="Password (min 8 characters)"
                />
                <div className="text-xs text-gray-500">
                  Note: Changing AP settings will restart the network service.
                </div>
                <Button
                  onClick={handleSaveAP}
                  disabled={!apName.trim() || !apPassword.trim() || apPassword.length < 8}
                  className="w-full"
                >
                  Save AP Settings
                </Button>
              </div>
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </Card>
  );
}