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
import { ThemeToggle } from "@/components/ThemeToggle";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import dynamic from "next/dynamic";

const PushToTalk = dynamic(() => import("@/components/PushToTalk"), {
  ssr: false,
});

const Listen = dynamic(() => import("@/components/Listen"), {
  ssr: false,
});

function GamepadPage() {
  const { selectedGamepadId } = useGamepadContext();

  return (
    <div className="container mx-auto p-4 max-w-6xl">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">
          <img src="/icon.png" alt="Logo" className="h-8 inline-block mr-2" />
          ByteRacer Control Panel</h1>
        <ThemeToggle />
      </div>

      {/* GamepadInputHandler renders invisibly to process controller inputs */}
      <GamepadInputHandler />

      <Tabs defaultValue="control" className="w-full">
        <TabsList className="mb-4">
          <TabsTrigger value="control">Control</TabsTrigger>
          <TabsTrigger value="gamepad">Gamepad</TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
          <TabsTrigger value="system">System</TabsTrigger>
          <TabsTrigger value="devtools">Dev Tools</TabsTrigger>
        </TabsList>

        <TabsContent value="control">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="md:col-span-2 space-y-4">
              <CameraFeed />
              <SensorData />
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="flex flex-col gap-4">
                  <div className="h-auto">
                  <TextToSpeech />
                  </div>
                  <div className="h-auto">
                  <Listen />
                  </div>
                </div>
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
        </TabsContent>

        <TabsContent value="gamepad">
          {selectedGamepadId ? (
            <GamepadPreview />
          ) : (
              <GamepadList />
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

        <TabsContent value="devtools">
          <LogViewer maxHeight="600px" />
          <DebugState />
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
