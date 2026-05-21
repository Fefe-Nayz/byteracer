# `gpt_manager.py`

## Role

`GPTManager` fait l'interface entre ByteRacer et OpenAI. C'est le module qui transforme une requete utilisateur en reponse structuree, puis en actions concretes sur le robot.

## Responsabilites

- gerer le thread de conversation et la continuite contextuelle;
- collecter texte, audio et image avant appel modele;
- envoyer la requete au modele OpenAI approprie;
- convertir la reponse en actions autorisees;
- executer fonctions predefinies, sequences moteur ou scripts Python;
- emettre des `gpt_status_update`, `gpt_response` et `speech_recognition`.

## Capacites couvertes

- prompt texte;
- appel avec image camera;
- transcription voix (`whisper-1`);
- voix de synthese IA (`gpt-4o-mini-tts`);
- mode conversationnel;
- annulation de requete;
- reset de conversation.

## API principale

- `create_new_conversation(websocket)`;
- `process_gpt_command(prompt, use_camera, websocket, new_conversation, use_ai_voice, conversation_mode)`;
- `cancel_gpt_command(websocket, conversation_mode)`;
- `execute_predefined_function(function_name, parameters, websocket, use_ai_voice)`;
- `cleanup()`;
- `restore_robot_state()`.

## Structure des actions

Les actions interpretees par le module sont volontairement limitees a:

- `none`
- `predefined_function`
- `motor_sequence`
- `python_script`

Cette reduction du champ d'action est un garde-fou central de l'integration.

## Interactions

- lit `ConfigManager` pour la cle API et les reglages IA;
- lit `CameraManager` pour joindre une image au modele;
- pilote `TTSManager` et `SoundManager` pour la restitution;
- pilote `AICameraCameraManager` pour les modes de vision/autonomie;
- passe par `script_runner.py` pour les scripts Python;
- repasse le robot en etat normal via `restore_robot_state()`.

## Fonctions predefinies notables

- mouvement: `move`, `move_forward`, `move_backward`, `turn`, `stop`;
- camera: `set_camera_angle`;
- capteurs: `get_distance`, `get_sensor_data`;
- modes AI: `start_face_tracking`, `start_traffic_sign_detection`, etc.;
- systeme et reseau;
- reglages dynamiques;
- animations via `preset_actions.py`.

## Points d'attention

- c'est aujourd'hui l'un des plus gros modules du depot;
- il melange preparation de prompt, appels API, orchestration, execution et restitution;
- toute evolution doit etre testee en mode sans camera, sans micro et sans cle API pour verifier les degradations gracieuses.

## Documents lies

- [../AI_INTEGRATION.md](../AI_INTEGRATION.md)
- [SCRIPT_RUNNER.md](SCRIPT_RUNNER.md)
- [PRESET_ACTIONS.md](PRESET_ACTIONS.md)
