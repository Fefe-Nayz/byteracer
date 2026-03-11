# `aicamera_manager.py`

## Role

`AICameraCameraManager` est le module de vision embarquee locale. Il s'occupe du suivi de visage, du suivi de couleur, de la detection YOLO et de la conduite autonome basee sur des regles.

## Responsabilites

- suivi de visage avec correction de direction et de distance;
- suivi de couleur;
- chargement d'un modele NCNN de detection;
- reconnaissance de feux, panneau stop et virage a droite;
- estimation de distance d'un objet detecte;
- execution de comportements autonomes;
- calibrations de virage a droite et de compensation moteur;
- patterns LED associes aux modes autonomes.

## API principale

- `start_face_following()` / `stop_face_following()`;
- `start_color_control()` / `stop_color_control()`;
- `start_traffic_sign_detection()` / `stop_traffic_sign_detection()`;
- `start_yolo_detection()` / `stop_yolo_detection()`;
- `calibrate_right_turn()` et `calibrate_right_turn_interactive(...)`;
- `calibrate_motors(command)`;
- setters AI: confidence, distance threshold, turn time, motor balance, speed, face tracking params.

## Boucles internes importantes

- `_face_follow_loop()`: boucle de tracking visage;
- `_color_control_loop()`: logique de suivi couleur;
- `_yolo_detection_loop()`: detection locale et prise de decision autonome;
- `_execute_right_turn()`: virage a droite avec LED et timing dedie.

## Priorites de la conduite autonome

Dans la boucle YOLO, le tri des evenements privilegie:

1. feux tricolores;
2. stop;
3. virage a droite;
4. sinon avance continue a `autonomous_speed`.

Les delays d'ignorance evitent les retriggers sur les memes panneaux ou feux.

## Reglages relies a `settings.json`

- `ai.yolo_confidence`
- `ai.distance_threshold_cm`
- `ai.turn_time`
- `ai.motor_balance`
- `ai.autonomous_speed`
- `ai.wait_to_turn_time`
- `ai.stop_sign_wait_time`
- `ai.stop_sign_ignore_time`
- `ai.traffic_light_ignore_time`
- `ai.target_face_area`
- `ai.forward_factor`
- `ai.face_tracking_max_speed`
- `ai.speed_dead_zone`
- `ai.turn_factor`

## Interactions

- s'appuie sur `CameraManager` pour les frames et l'affichage overlay;
- commande `Picarx` directement pour les mouvements autonomes;
- lit `SensorManager` pour rester coherent avec la securite globale;
- utilise `TTSManager` et `LEDManager` pour des retours utilisateur;
- peut etre pilote par `GPTManager` via des actions predefinies.

## Point fort technique

La logique autonome est locale, deterministic et reglable. Cela permet des demos robustes meme sans connexion OpenAI, tout en gardant l'IA generative comme couche de commande plus haut niveau.
