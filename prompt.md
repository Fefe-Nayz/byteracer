# Prompt – Synthèse du Projet

## 1. Présentation Générale

Le projet est un TIPE dont l’objectif est la conception d’un **robot pilotable via une interface web** (sunfounder Picar-X) en utilisant une manette de jeu. Il s’appuie sur trois composantes principales :

- **ByteRacer** : La partie "robot" en Python qui gère le contrôle (vitesse, direction, TTS, gestion de la caméra, etc.).
- **EagleControl** : Un serveur WebSocket en TypeScript qui gère la communication en temps réel entre le robot et les interfaces.
- **RelayTower** : L’interface web (basée sur Next.js, react, shadcnui, tailwind CSS) qui offre un tableau de bord complet pour piloter le robot et visualiser l’état de ses capteurs, son flux vidéo et d’autres données de debug.

## 2. Architecture et Structure du Projet

Le dépôt est organisé en trois dossiers principaux :

```
nayzflux-byteracer/
├── byteracer/         # Code Python : gestion du robot, TTS, caméra, commandes système…
├── eaglecontrol/      # Code TypeScript : serveur WebSocket pour la communication temps réel
└── relaytower/        # Application Next.js : interface web pour le contrôle et le monitoring
```

### ByteRacer
- **main.py** : Point d’entrée du service Python qui initialise les capteurs, la caméra, le TTS et les commandes reçues via WebSocket.
- **requirements.txt**, **install.sh** et autres scripts système : Gestion des dépendances et de l’installation.

### EagleControl
- **index.ts** : Implémentation du serveur WebSocket permettant de relayer les messages entre le robot et le client.
- **package.json**, **tsconfig.json** et **bun.lock** : Configuration de l’environnement TypeScript/Bun.

### RelayTower
- **src/** : Contient la partie front-end en React avec des composants dédiés (caméra, liste de manettes, debug, remapping, etc.).
- **app/** : Pages et mise en page de l’application Next.js.
- **components/ui/** : Bibliothèque de composants UI (boutons, cartes, champs, etc.) construits avec Tailwind CSS, Radix UI et shadcn/ui.
- **contexts/** et **hooks/** : Gestion de l’état du gamepad, stockage local et logique métier pour la communication et le mapping des commandes.

### Autres fichiers
- **startup.sh** : Script de démarrage pour initialiser les services Python et TypeScript.

### Autres fichiers utiles
- **/byteracer/scripts/** : Dossier contenant des scripts bash utilisés pour répondre à des commandes système (redémarrage, mise à jour, etc.).
- **/byteracer/logs/** : Dossier contenant les fichiers de log générés par le service Python.
- **/byteracer/tts/** : Dossier contenant un script Python pour le TTS (Text-to-Speech) qui pourra être utilisé dans les scripts bash.
- **/byteracer/assets/** : Dossier contenant les fichiers audio utilisés pour les sons du robot.


## 3. Fonctionnalités Clés

- **Contrôle en temps réel** : Le robot reçoit des commandes (via des entrées de manette) qui sont traitées par le module ByteRacer et relayées par EagleControl vers RelayTower.
- **Interface Web Responsive** : RelayTower permet la visualisation du flux vidéo de la caméra, l’état des capteurs (vitesse, boutons, axes) et la gestion des remappings personnalisés.
- **Système de Notifications Vocales** : Utilisation d’un TTS pour informer l’utilisateur de l’état du robot ou de commandes système (redémarrage, erreurs…).
- **Gestion des Mises à Jour** : Des scripts dédiés permettent la mise à jour des différents services (Python, WebSocket, Web Server) avec retour d’information via le TTS et l’interface.

## 4. Consignes de Mise à Jour et Améliorations Futures

Les points de mise à jour et d’amélioration identifiés incluent notamment :

- **TTS asynchrone** : Optimiser l’exécution du TTS pour qu’il ne bloque pas le reste du programme.
- **Retour d’information enrichi** : Améliorer le contenu des messages vocaux afin d’offrir une meilleure expérience utilisateur (infos utiles lors des commandes système).
- **Notification du démarrage** : Utiliser un script dédié en Python pour notifier l’utilisateur de l’avancement du démarrage via le TTS.
- **Gestion de la connexion/disconnexion** :
  - Éviter la répétition incessante de l’adresse IP.
  - Interrompre le fonctionnement et notifier par TTS en cas de déconnexion du client ou d’inactivité prolongée.
- **Prévention des collisions** : Utilisation des capteurs (ultrasons, suivi de ligne) pour empêcher le robot de heurter des obstacles ou de tomber.
- **Gestion de la batterie** : Notification par TTS régulière en cas de faible batterie.
- **Redémarrage automatique de la caméra** : Détection des problèmes de flux et redémarrage automatique avec notification sur l’interface (panneau d’alerte sur le flux vidéo).
- **Commandes systèmes depuis l’interface** : Le client peut envoyer diverses commandes (redémarrage du robot, des services, vérification des mises à jour, etc.) avec retour visuel et vocal.

## 5. Perspectives Techniques et Intégration

- **Modularisation** : Le code Python de ByteRacer a été refactorisé en plusieurs modules pour une meilleure maintenance.
- **Intégration avec ChatGPT** : Possibilité d’envoyer des prompts (texte ou audio) pour piloter des actions spécifiques (faire danser le robot, déclencher des sons, etc.).
- **Système Audio Avancé** : Ajout de sons réalistes pour l’accélération, le freinage et le drift, avec gestion de variations et coupure au moment opportun.
- **Fichier Log** : Implémentation d’un fichier log avec horodatage et nettoyage automatique.

## 6. Consignes pour les mises à jours demandées
- Choses à améliorer:
    - Le TTS doit être asynchrone pour ne pas bloquer le reste du programme
    - Ce qui est dit par le robot doit être amélioré pour une meilleur experience (des informations plus utiles)
    - Dans le script de démarrage nous devons utiliser le TTS pour notifier à l'utilisateur l'avancement du démarrage (via un script Python TTS dédié appelé depuis le bash)
    - Arrêter de répéter l'adresse IP en boulcle dès que le client se connecte au websocket, pas seulement après avoir reçu des inputs
    - Si le client se déconnecte, si la manette se déconnecte ou si le robot ne recoit plus d'instructions pendant un certain temps. Il doit s'arrêter et dire avec le TTS "Emergency stop, client disconnected"
    - Le robot doit éviter de rentrer dans des obstacles ou de tomber d'un support grace à ses capteurs ultrasons et de suivi de ligne qui font également office de "capteur de vide". Si l'utilisateur vas en direction d'un obstacle ou s'apprette à tomber dans un trou, le robot prends le dessus et l'empêche de se crasher dedans en s'arrêtant et en reculant un petit peu, une fois le danger passé l'utilisaateur peu à nouveu controler le robot. Le robot doit également dir "Emergency stop, obstacle detected, backing up"
    - Si le robot à peu de batterie il demandera une fois par minute via le TTS de le recharger
    - Si la caméra à un problème, que le flux est interrompu ou que le réseau wifi/point d'accès est changé nous devons redémarrer la caméra, si cela arrive le client doit être notifié pour avertir l'utilisateur (Un panneau d’alerte visuelle est affiché sur le flux vidéo par exemple)
- Contrôle et communication depuis le client:
    - Le client peut voir les données des capteurs de vitesse (en intégrant l'accélération et en recalibrant quand la vitesse est nulle), ultrason et suivi de ligne
    - Le client peut voir lorsque le robot reprends le dessus à cause d'un emergency stop
    - Le client peut voir l'état de la caméra et peut la redémarrer si elle ne réponds plus
    - Le client peut régler le niveau sonore du robot (pour les sons et le TTS) et peut activer/désactiver le TTS si besoin
    - Le client peut activer/désactiver "l'aide à la conduite" (prévention de crash)
    - Le client peut activer/désactiver le tracking et suivi de personne
    - Le client peut activer/désactiver le mode circuit (détection de panneaux, feux et obstacles et sortie de route -suivi de ligne-) où l'ulilisateur conduit mais le robot le force à respecter les panneaux etc.
    - Le client peut modifier les paramètres réseau du robot en basculant entre WIFI et Point d'accès, ainsi que d'ajouter des réseaux wifi, et en supprimer
    - Le client peut envoyer différentes commandes comme: Redémarrer le robot entierement, Arrêter le robot, Redémarrer tout les services (Serveur Web pour le site, Serveur Web Socket et Script python), redémarrer chaque service indépendament et redémarrer le flux caméra et rechercher des mises à jour sur le dépot github.
        - Chaque commande est un script bash spécifique. Nous devons faire des retours constants à l'utilisateur sur l'avancée des commandes via TTS (via un script Python TTS dédié appelé depuis le bash)
        - Un état d'avancement plus basique (loading, failed, succeeded) est envoyé au client pour gérer l'état de chargement des boutons
        - Pour les mises à jour il faudrait un peu plus de contexte (pas de mise à jour, mise à jour trouvée, installation et quand le script python redémarre il envoie automatiquement au client maj suceeded et python restart suceeded always in case it was trigerred)
        - Pour le redémarrage du python tout doit se faire également en bash mais juste avant de se fermer il envoie un succeded au client puis exécute un bash qui ferme et réouvre le script python
    - L'état des paramètres utilisateur est sauvegardé dans un fichier JSON sur le robot qui permet de retrouver les paramètres après un redémarrage. Le client adopte aussi ces paramètres qui lui sont envoyés lors de la connection
- Le scipt python est refactorisé dans plusieurs fichiers responsables chaqun d'une partie du fonctionnement
- Un nouveu text field qui permet d'envoyer qqc que le robot doit lire avec le TTS
- Intégration avec ChatGPT (envoi de prompts texte ou oral si micro et agis en conséquences avec le flux vidéo), exemple fait dancer le robot (chat gpt envera des commandes au robot pour le faire dancer), fait le chanter et il envoie un texte à dire avec TTS, que vois tu (regarde le flux video et dit avec le TTS ce qu'il voit) etc etc
- Lorsque le robot accélère il doit jouer un son d'accélération de voiture, un son de frein lorque l'on freine et un son de drift quand on tourne. Trouver un système pour que ces sons parissent naturels (plusieurs variations, couper le son dès l'arrêt de l'accélération..., passage des rapports)
- Pouvoir déclancher un son avec l'appui d'une touche avec un son customisable depuis le client parmis une liste prédéfinie (pet, klaxon, alram sound, memes etc.), utilisation d'un soundController pour controller tout les sons et les TTS. Utilisation de pygame pour les sons
- Fichier log avec timestamp et nettoyage automatique
- Mode démonstration
---

# TODO:
PUR PYTHON:
- Implémenter l'intégration avec chatGPT https://docs.sunfounder.com/projects/picar-x-v20/fr/latest/openai.html#modification-des-parametres-facultatif
- Pouvoir afficher une session "SSH" via websocket sur l'interface utilisateur (taper des commandes directement sur l'interface utilisateur)

AUTRES:
- Ajout d'un micro avec transmission audio (https://www.sunfounder.com/products/mini-usb-microphone?_pos=1&_sid=f7cb6af2f&_ss=r)


Gerardo :
- Implémenter le mode démo (envoi de commandes préenregistrées au robot pour le faire avancer, tourner, reculer, freiner, etc.)
- Implémenter le suivi de personne (détection de visage et suivi de la personne avec la caméra)
- Implémenter le mode circuit (détection de panneaux, feux et obstacles et sortie de route -suivi de ligne-)

## Conclusion

Ce document de synthèse (prompt.md) permet de présenter l’architecture globale du projet ainsi que les axes principaux d’amélioration. Il sert de point de départ pour les développements ultérieurs, les tests et les présentations lors des rendus.