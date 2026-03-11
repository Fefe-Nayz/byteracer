# `led_manager.py`

## Role

`LEDManager` pilote le retour lumineux embarque. C'est un module simple mais tres utilise par les autres briques pour signaler un etat localement.

## Responsabilites

- allumer, eteindre et toggler la LED;
- clignoter un nombre fini de fois;
- lancer et arreter un clignotement continu;
- respecter le flag global `led.enabled`.

## API principale

- `turn_on()`;
- `turn_off()`;
- `toggle()`;
- `blink(times, interval)`;
- `start_blinking(interval)`;
- `stop_blinking(led_on=False)`;
- `set_enabled(enabled)`.

## Interactions

- `SensorManager` peut signaler un etat d'alerte;
- `AICameraCameraManager` s'en sert pour le suivi, le stop light et les clignotants;
- `ByteRacer` le configure via `ConfigManager`.

## Point d'attention

Le module est simple, mais il devient un point de couplage indirect des modes autonomes. Une modification de comportement LED doit etre testee avec les sequences IA qui s'appuient sur lui.
