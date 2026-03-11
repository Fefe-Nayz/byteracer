# `sensor_manager.py`

## Role

`SensorManager` est le gardien de securite du robot. Il surveille les capteurs physiques, maintient l'etat du robot et corrige ou bloque les commandes de mouvement quand une urgence est detectee.

## Etats suivis

### `RobotState`

- `INITIALIZING`
- `STANDBY`
- `MANUAL_CONTROL`
- `EMERGENCY_CONTROL`
- `GPT_CONTROLLED`
- `CIRCUIT_MODE`
- `DEMO_MODE`
- `TRACKING_MODE`

### `EmergencyState`

- `COLLISION_FRONT`
- `EDGE_DETECTED`
- `CLIENT_DISCONNECTED`
- `LOW_BATTERY`
- `MANUAL_STOP`

## Responsabilites

- lire l'ultrason, les capteurs de ligne et le niveau batterie;
- surveiller les timeouts de client;
- declencher l'urgence appropriee;
- executer la logique de clearance quand une urgence disparait;
- appliquer des contraintes de securite a `speed` et `turn_angle`;
- fournir un snapshot complet via `get_sensor_data()`.

## API principale

- `start()` / `stop()`;
- `update_motion(speed, turn_angle)`;
- `register_client_connection()` / `register_client_input()` / `client_disconnect()`;
- `manual_emergency_stop()` / `clear_manual_stop()`;
- `trigger_emergency()` / `update_battery_level()`;
- setters de configuration: collision, edge detection, cooldown, distance buffer, batterie, tracking, circuit mode, demo mode.

## Boucles internes

- `_monitor_sensors()`: boucle de supervision principale;
- `_update_sensor_readings()`: acquisition des mesures;
- `_check_emergency_conditions()`: detection des seuils critiques;
- `_handle_emergency()` et `_check_emergency_clearance()`: prise de controle et retour a la normale.

La cadence de supervision est de l'ordre de `50 ms`.

## Interactions

- callback vers `ByteRacer.handle_emergency()`;
- lit et pilote `Picarx` pour forcer un stop ou un recul de securite;
- active `LEDManager` pour certains retours visuels;
- alimente `sensor_data` consomme par le front.

## Point fort technique

La logique d'urgence est au meme niveau de priorite que le manuel et l'IA. Cela signifie qu'une commande GPT ou manette ne peut pas contourner un stop de securite simplement parce qu'elle a ete demandee plus tard.
