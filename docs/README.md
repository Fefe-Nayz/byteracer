# Documentation ByteRacer

Ce dossier regroupe la documentation technique de reference du projet. Il couvre l'installation Raspberry Pi, l'architecture logicielle, la web app, l'integration IA et un detail module par module du service Python.

## Guides principaux

- [INSTALLATION.md](INSTALLATION.md): preparation du Raspberry Pi, installation de la pile SunFounder, services JS/Python, calibrations et demarrage automatique.
- [ARCHITECTURE.md](ARCHITECTURE.md): vue systeme des trois services, cycle de vie et responsabilites.
- [MODULE_COMMUNICATIONS.md](MODULE_COMMUNICATIONS.md): callbacks internes, protocole WebSocket et rythmes de mise a jour.
- [MAIN_ORCHESTRATOR.md](MAIN_ORCHESTRATOR.md): lecture detaillee de `byteracer/main.py`.
- [WEB_APP.md](WEB_APP.md): structure de `relaytower`, gestion du WebSocket, gamepad, audio et pages.
- [AI_INTEGRATION.md](AI_INTEGRATION.md): ChatGPT, scripts Python controles, vision embarquee, suivi de visage et conduite autonome.

## Documentation des modules Python

- [PYTHON_MODULES/README.md](PYTHON_MODULES/README.md): index des modules et dependances.
- [PYTHON_MODULES/CONFIG_MANAGER.md](PYTHON_MODULES/CONFIG_MANAGER.md)
- [PYTHON_MODULES/SENSOR_MANAGER.md](PYTHON_MODULES/SENSOR_MANAGER.md)
- [PYTHON_MODULES/CAMERA_MANAGER.md](PYTHON_MODULES/CAMERA_MANAGER.md)
- [PYTHON_MODULES/AICAMERA_MANAGER.md](PYTHON_MODULES/AICAMERA_MANAGER.md)
- [PYTHON_MODULES/GPT_MANAGER.md](PYTHON_MODULES/GPT_MANAGER.md)
- [PYTHON_MODULES/AUDIO_MANAGER.md](PYTHON_MODULES/AUDIO_MANAGER.md)
- [PYTHON_MODULES/SOUND_MANAGER.md](PYTHON_MODULES/SOUND_MANAGER.md)
- [PYTHON_MODULES/TTS_MANAGER.md](PYTHON_MODULES/TTS_MANAGER.md)
- [PYTHON_MODULES/NETWORK_MANAGER.md](PYTHON_MODULES/NETWORK_MANAGER.md)
- [PYTHON_MODULES/LOG_MANAGER.md](PYTHON_MODULES/LOG_MANAGER.md)
- [PYTHON_MODULES/LED_MANAGER.md](PYTHON_MODULES/LED_MANAGER.md)
- [PYTHON_MODULES/SCRIPT_RUNNER.md](PYTHON_MODULES/SCRIPT_RUNNER.md)
- [PYTHON_MODULES/PRESET_ACTIONS.md](PYTHON_MODULES/PRESET_ACTIONS.md)

## Medias de presentation

Les images et videos extraites de la presentation sont stockees dans `docs/media/presentation/`. Les diagrammes et visuels extraits du synoptique Word sont stockes dans `docs/media/synoptic/`. Ces assets servent a illustrer le README GitHub et peuvent etre reutilises dans d'autres pages du depot.
