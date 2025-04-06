"use client";
import { GamepadProvider } from "@/contexts/GamepadContext";
import { WebSocketProvider } from "@/contexts/WebSocketContext";
import { useGamepadContext } from "@/contexts/GamepadContext";
import GamepadList from "@/components/GamepadList";
import GamepadPreview from "@/components/GamepadPreview";
import WebSocketStatus from "@/components/WebSocketStatus";
import DebugState from "@/components/DebugState";
import CameraFeed from "@/components/CameraFeed";
import SensorData from "@/components/SensorData";
import RobotControls from "@/components/RobotControls";
import RobotSettings from "@/components/RobotSettings";
import TextToSpeech from "@/components/TextToSpeech";
import SoundEffects from "@/components/SoundEffects";
import GptIntegration from "@/components/GptIntegration";
import NetworkSettings from "@/components/NetworkSettings";
import GamepadInputHandler from "@/components/GamepadInputHandler";
import LogViewer from "@/components/LogViewer";
import RobotModeIndicator from "@/components/RobotModeIndicator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import dynamic from "next/dynamic";

const PushToTalk = dynamic(() => import("@/components/PushToTalk"), {
  ssr: false,
});

function GamepadPage() {
  const { selectedGamepadId } = useGamepadContext();

  return (
    <div className="container mx-auto p-4 max-w-6xl">
      <h1 className="text-2xl font-bold mb-6">ByteRacer Control Panel</h1>

      {/* GamepadInputHandler renders invisibly to process controller inputs */}
      <GamepadInputHandler />

      <Tabs defaultValue="control" className="w-full">
        <TabsList className="mb-4">
          <TabsTrigger value="control">Control</TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
          <TabsTrigger value="system">System</TabsTrigger>
          <TabsTrigger value="features">Features</TabsTrigger>
          <TabsTrigger value="debug">Debug</TabsTrigger>
          <TabsTrigger value="logs">Logs</TabsTrigger>
        </TabsList>

        <TabsContent value="control">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="md:col-span-2 space-y-4">
              <CameraFeed />
              <SensorData />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <TextToSpeech />
                <SoundEffects />
              </div>
            </div>

            <div className="space-y-4">
              <GamepadList />
              <WebSocketStatus />
              <RobotControls />
              <GptIntegration />
              <PushToTalk />
              <RobotModeIndicator />
            </div>
          </div>

          {/* Only show preview if a gamepad is selected */}
          {selectedGamepadId && (
            <div className="mt-6">
              <GamepadPreview />
            </div>
          )}
        </TabsContent>

        <TabsContent value="settings">
          <RobotSettings />
        </TabsContent>

        <TabsContent value="system">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <h2 className="text-xl font-semibold mb-4">System Controls</h2>
              <RobotControls showAllControls={true} />
            </div>
            <div>
              <h2 className="text-xl font-semibold mb-4">Network Settings</h2>
              <NetworkSettings />
            </div>
          </div>
        </TabsContent>
        
        <TabsContent value="features">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="space-y-6">
              <TextToSpeech />
              <SoundEffects />
            </div>
            <div>
              <GptIntegration />
            </div>
          </div>
        </TabsContent>

        <TabsContent value="debug">
          <DebugState />
        </TabsContent>

        <TabsContent value="logs">
          <LogViewer maxHeight="600px" />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default function GamepadPageWithProvider() {
  return (
    <WebSocketProvider>
      <GamepadProvider>
        <GamepadPage />
      </GamepadProvider>
    </WebSocketProvider>
  );
}
