import { useState, useEffect } from "react";
import { useWebSocket, RobotSettings } from "@/contexts/WebSocketContext";
import { Card } from "./ui/card";
import { Input } from "./ui/input";
import { Button } from "./ui/button";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import { Wifi, Globe, Loader2, PlusCircle, Trash2 } from "lucide-react";
import { useToast } from "@/hooks/use-toast";

type NetworkMode = "wifi" | "ap";
type WifiNetwork = { ssid: string; password: string };

export default function NetworkSettings() {

  const { toast } = useToast();
  const { status, settings, updateSettings, scanNetworks, updateNetwork, requestSettings } = useWebSocket();
  
  // Local state for form values
  const [mode, setMode] = useState<NetworkMode>("wifi");
  const [apName, setApName] = useState("");
  const [apPassword, setApPassword] = useState("");
  const [knownNetworks, setKnownNetworks] = useState<WifiNetwork[]>([]);
  const [newSsid, setNewSsid] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [availableNetworks, setAvailableNetworks] = useState<string[]>([]);
  const [isScanning, setIsScanning] = useState(false);
  
  // Update local state when we get settings from server
  useEffect(() => {
    if (settings?.network) {
      setMode(settings.network.mode);
      setApName(settings.network.ap_name);
      setApPassword(settings.network.ap_password);
      setKnownNetworks([...settings.network.known_networks]);
    }
  }, [settings]);
  
  // Request settings when component mounts or reconnects
  useEffect(() => {
    if (status === "connected") {
      requestSettings();
    }
  }, [status, requestSettings]);
  
  // Listen for network scan results
  useEffect(() => {
    const handleNetworkList = (event: CustomEvent) => {
      if (event.detail && Array.isArray(event.detail.networks)) {
        setAvailableNetworks(event.detail.networks);
        setIsScanning(false);
        
        toast({
          title: "Network scan complete",
          description: `Found ${event.detail.networks.length} networks`,
          duration: 3000,
        });
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
  }, [toast, setIsScanning, setAvailableNetworks]);
  
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
    
    // Add to local state
    const newNetwork = { ssid: newSsid, password: newPassword };
    const updatedNetworks = [...knownNetworks, newNetwork];
    setKnownNetworks(updatedNetworks);
    
    // Send update to robot
    updateNetwork("add_network", newNetwork);
    
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
    // Update local state
    const updatedNetworks = knownNetworks.filter(n => n.ssid !== ssid);
    setKnownNetworks(updatedNetworks);
    
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
    
    // Create a partial settings object for update
    const networkSettings: Partial<RobotSettings> = {
      network: {
        mode: "ap",
        ap_name: apName,
        ap_password: apPassword,
        known_networks: knownNetworks
      }
    };
    
    // Update settings
    updateSettings(networkSettings);
    
    toast({
      title: "AP settings saved",
      description: "Access Point settings updated",
      duration: 3000,
    });
  };
  
  // Change network mode
  const handleModeChange = (newMode: NetworkMode) => {
    // Create a partial settings object for update
    const networkSettings: Partial<RobotSettings> = {
      network: {
        mode: newMode,
        ap_name: apName,
        ap_password: apPassword,
        known_networks: knownNetworks
      }
    };
    
    // Update settings and local state
    setMode(newMode);
    updateSettings(networkSettings);
    
    toast({
      title: "Network mode changed",
      description: `Switched to ${newMode === "wifi" ? "WiFi" : "Access Point"} mode`,
      duration: 3000,
    });
  };
  
  // Use a network from the scan results
  const handleUseNetwork = (ssid: string) => {
    setNewSsid(ssid);
  };
  
  // If not connected, show placeholder
  if (status !== "connected" || !settings) {
    return (
      <Card className="p-4">
        <h3 className="font-bold mb-3">Network Settings</h3>
        <div className="text-sm text-gray-500 italic">
          {status === "connected" 
            ? "Loading settings..." 
            : "Connect to robot to view network settings"}
        </div>
      </Card>
    );
  }
  
  return (
    <Card className="p-4">
      <div className="flex items-center space-x-2 mb-4">
        <Globe className="h-5 w-5" />
        <h3 className="font-bold">Network Settings</h3>
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
              <h4 className="text-sm font-medium mb-2">Add New Network</h4>
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
                <Button
                  onClick={handleAddNetwork}
                  disabled={!newSsid.trim() || !newPassword.trim()}
                  className="w-full"
                >
                  <PlusCircle className="h-4 w-4 mr-2" />
                  Add Network
                </Button>
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
                    {availableNetworks.map((ssid) => (
                      <div
                        key={ssid}
                        className="flex justify-between items-center p-2 hover:bg-muted/50 rounded cursor-pointer"
                        onClick={() => handleUseNetwork(ssid)}
                      >
                        <div className="flex items-center space-x-2">
                          <Wifi className="h-4 w-4" />
                          <span className="text-sm">{ssid}</span>
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
                    ))}
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