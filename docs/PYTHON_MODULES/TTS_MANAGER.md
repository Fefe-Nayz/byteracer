# `tts_manager.py`

## Role

`TTSManager` gere la parole locale du robot. Il fait de la synthese vocale asynchrone, avec file d'attente et priorites.

## Responsabilites

- accepter des requetes `say(...)` non bloquantes;
- gerer une file de messages avec priorite;
- generer des fichiers WAV temporaires;
- jouer la parole via l'infrastructure audio locale;
- nettoyer les fichiers temporaires;
- exposer des reglages de volume dedies aux messages utilisateur, systeme et urgence.

## API principale

- `start()` / `stop()`;
- `say(text, priority=..., blocking=False, lang=None)`;
- `stop_speech()`;
- `is_speaking()`;
- `clear_queue(min_priority=...)`;
- `set_enabled()`, `set_language()`, `set_volume()`;
- `set_user_tts_volume()`, `set_system_tts_volume()`, `set_emergency_tts_volume()`.

## Interactions

- `startup.sh` utilise aussi le script `byteracer/tts/speak.py` pour annoncer le boot;
- `ByteRacer` l'utilise pour les messages de pret, d'IP et d'etat;
- `SensorManager` et `GPTManager` l'utilisent pour les retours critiques ou conversationnels;
- `AICameraCameraManager` s'en sert pour certaines annonces de mode autonome.

## Point d'attention

Le module doit cohabiter avec les sons et la voix IA. Toute modification de canaux ou de volume doit etre verifiee avec `SoundManager` pour eviter les conflits audio.
