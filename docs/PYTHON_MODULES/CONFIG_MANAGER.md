# `config_manager.py`

## Role

`ConfigManager` est la couche de persistance de ByteRacer. Il charge, expose, fusionne et sauvegarde `settings.json`.

## Responsabilites

- initialiser la configuration par defaut si aucun fichier n'existe;
- exposer des acces `get(path)` / `set(path, value)` sur une structure JSON imbriquee;
- maintenir une liste de reseaux Wi-Fi connus;
- sauvegarder les modifications de maniere differee via une tache d'autosave;
- permettre un reset total ou par section.

## API principale

- `start()` / `stop()`: cycle de vie du gestionnaire;
- `get(path)`: lecture d'une valeur via un chemin de type `section.cle`;
- `set(path, value)`: ecriture d'une valeur et marquage pour sauvegarde;
- `save()`: demande de sauvegarde;
- `reset_to_defaults(section)`: reinitialisation partielle ou complete;
- `add_known_network()` / `remove_known_network()`: edition du carnet Wi-Fi.

## Sections de configuration importantes

- `sound`
- `camera`
- `safety`
- `drive`
- `modes`
- `github`
- `api`
- `ai`
- `led`

## Dependances et interactions

- lu et ecrit par `ByteRacer` lors du boot et des mises a jour de settings;
- consomme par `GPTManager`, `AICameraCameraManager`, `TTSManager`, `SoundManager`, `CameraManager`, `SensorManager` et `LEDManager`;
- sert de point de verite pour l'interface `RobotSettings.tsx`.

## Points d'attention

- toute nouvelle cle ajoutee cote front doit etre prise en charge ici;
- `startup.sh` lit directement une partie des valeurs Git dans le fichier JSON;
- une modification de structure de `settings.json` a des effets sur le front, le boot script et plusieurs modules Python.
