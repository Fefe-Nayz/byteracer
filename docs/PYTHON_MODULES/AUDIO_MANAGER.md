# `audio_manager.py`

## Role

`AudioManager` gere le flux audio sortant du robot vers le navigateur. Il capture le micro local et l'envoie en chunks WAV base64 via WebSocket.

## Responsabilites

- detecter un peripherique d'entree disponible;
- demarrer et arreter l'enregistrement;
- capturer des frames audio courtes;
- assembler des paquets d'environ `250 ms`;
- encoder et envoyer les chunks `audio_stream` vers le front.

## API principale

- `set_websocket(websocket)`;
- `start()` / `stop()`;
- `start_recording(websocket)`;
- `stop_recording()`.

## Pipeline interne

- callback PyAudio ou lecture blocking selon le device;
- file de capture PCM;
- boucle d'encodage;
- boucle d'emission WebSocket.

## Interactions

- demarre sous le controle de `ByteRacer`;
- alimente `Listen.tsx` cote front;
- partage l'infrastructure WebSocket avec le reste des messages temps reel.

## Point d'attention

Le projet utilise aussi un autre flux `audio_stream` dans l'autre sens pour le push-to-talk. Il faut donc bien distinguer:

- `data.audio` pour navigateur -> robot;
- `data.audioData` pour robot -> navigateur.
