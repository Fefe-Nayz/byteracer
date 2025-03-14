import { Card } from "./ui/card";

export default function GamepadEmptyState() {
  return (
    <Card className="flex items-center justify-center p-4 h-[400px]">
      <p className="font-semibold">Aucune manette connectée</p>
      <p>Connecter une manette pour commencer une partie</p>
    </Card>
  );
}
