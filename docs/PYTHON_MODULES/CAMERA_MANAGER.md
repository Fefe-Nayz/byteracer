# `camera_manager.py`

## Role

`CameraManager` encapsule `Vilib` et `Picamera2`. Il gere l'ouverture de la camera, l'exposition du flux MJPEG et la detection de gel du pipeline video.

## Etats

- `INACTIVE`
- `STARTING`
- `RUNNING`
- `ERROR`
- `RESTARTING`
- `FROZEN`

## Responsabilites

- demarrer `Vilib.camera_start(...)`;
- activer l'affichage local et/ou web;
- surveiller periodiquement la fraicheur des frames;
- redemarrer completement la camera si besoin;
- basculer les modes de detection legers de `Vilib`;
- exposer l'etat courant au reste du systeme.

## API principale

- `start(status_callback)` / `stop()`;
- `restart()`;
- `get_status()`;
- `update_settings(vflip, hflip, local, web, camera_size)`;
- `switch_face_detect(enable)`;
- `color_detect(color)` et `switch_color_detect(enable)`;
- `switch_trafic_sign_detect(enable)`;
- `display_yolo_detections_on_vilib(...)`;
- `disable_vilib_drawing()`.

## Logique de freeze detection

Le module:

- echantillonne regulierement des images;
- compare les frames sur une fenetre d'environ `5 s`;
- bascule l'etat en `FROZEN` si le flux semble immobile de maniere anormale;
- notifie `ByteRacer`, qui peut ensuite renvoyer `camera_status` au front.

## Interactions

- `ByteRacer` l'utilise comme source primaire de video;
- `AICameraCameraManager` lit les images qu'il expose;
- `GPTManager` peut demander une capture pour les appels OpenAI;
- `RelayTower` consomme le flux via `http://<host>:9000/mjpg`.

## Point d'attention

Le flux camera est volontairement hors WebSocket. Cela simplifie le transport video, mais oblige a superviser separement la sante du flux et la sante du bus temps reel.
