# `sound_manager.py`

## Role

`SoundManager` pilote les sons embarques du robot: bruitages de conduite, alertes, fichiers custom et playback d'audio entrant.

## Responsabilites

- charger les bibliotheques de sons depuis `byteracer/assets/`;
- jouer et stopper des sons par categorie;
- ajuster les volumes globaux et par famille;
- faire varier certains sons selon vitesse, braquage et acceleration;
- lire un fichier audio ou un flux vocal recu du navigateur.

## API principale

- `play_sound(sound_type, loop=False, name=None)`;
- `stop_sound(sound_type, channel_id=None)`;
- `update_driving_sounds(speed, turn_value, acceleration)`;
- `play_alert(alert_name)`;
- `play_custom_sound(sound_name)`;
- `play_voice_stream(file_path)`;
- `play_file(file_path, blocking=False)`;
- `set_enabled()`, `set_volume()`, `set_category_volume()`, `shutdown()`.

## Interactions

- `ByteRacer` l'utilise pendant le pilotage manuel;
- `TTSManager` reserve des canaux audio et s'appuie sur lui pour la restitution;
- `GPTManager` peut declencher des sons ou jouer une voix IA synthetisee;
- le flux push-to-talk navigateur -> robot finit ici pour lecture locale.

## Point fort

La separation entre `SoundManager` et `TTSManager` evite de melanger bruitages et parole, tout en permettant un arbitrage de volume plus fin.
