# Installation Du Projet

## Objectif

Cette documentation decrit une installation complete sur Raspberry Pi pour le mode cible du projet:

- `ByteRacer` sur Python pour le pilotage materiel;
- `EagleControl` sur Bun/Hono pour le bus WebSocket;
- `RelayTower` sur Next.js pour l'interface operateur.

Elle integre la sequence historique de setup du Picar-X, les etapes manquantes qui ne sont pas couvertes par `byteracer/install.sh`, les calibrations a realiser avant la premiere utilisation et le demarrage automatique via `startup.sh`.

## 1. Vue d'ensemble du flow

Pour un Raspberry Pi neuf, la sequence recommandee est la suivante:

1. preparer Raspberry Pi OS et activer les interfaces necessaires;
2. installer les dependances systeme;
3. installer la pile SunFounder (`robot-hat`, `vilib`, `picar-x`);
4. activer l'audio I2S et le bus I2C;
5. calibrer les servos et les capteurs du Picar-X;
6. installer Bun, puis optionnellement Node.js;
7. cloner uniquement l'applicatif dans `/home/pi/ByteRacer`;
8. installer `relaytower`, `eaglecontrol` et `byteracer`;
9. configurer la cle OpenAI si l'IA doit etre activee;
10. installer les services `systemd`, les protections de carte SD et, si besoin, le mode point d'acces.

## 2. Prerequis

### Materiel cible

- un Raspberry Pi compatible `Picamera2`;
- un SunFounder Picar-X complet;
- une camera compatible Pi Camera / `Picamera2`;
- facultatif: microphone USB pour l'ecoute distante et le mode conversationnel GPT;
- facultatif: sortie audio / ampli si le robot doit parler ou jouer des sons.

### OS et hypothese d'installation

- Raspberry Pi OS ou Debian avec acces `sudo`;
- utilisateur principal: `pi`;
- repertoire final du projet: `/home/pi/ByteRacer`;
- `NetworkManager` / `nmcli` disponibles si vous souhaitez piloter le Wi-Fi et le point d'acces depuis l'interface.

## 3. Preparation du Raspberry Pi

### 3.1 Activer les interfaces utiles

Avant toute installation, ouvrir `raspi-config`:

```bash
sudo raspi-config
```

Activer au minimum:

- `Interface Options -> VNC` pour l'acces distant graphique;
- `Interface Options -> I2C` pour la carte et les capteurs Picar-X.

Vous pouvez aussi activer `SSH` si vous administrez le robot a distance uniquement en terminal.

### 3.2 Mettre le systeme a jour

```bash
sudo apt update
sudo apt upgrade -y
sudo apt autoremove -y
```

### 3.3 Installer les paquets systeme de base

```bash
sudo apt install -y \
  git curl jq screen mc sox libsox-fmt-all libttspico-utils \
  raspi-config i2c-tools espeak alsa-utils pulseaudio pulseaudio-utils \
  python3 python3-pip python3-dev python3-setuptools python3-wheel \
  python3-smbus \
  python3-websockets python3-psutil python3-pygame python3-pyaudio \
  python3-numpy python3-pil portaudio19-dev
```

Si vous utilisez la gestion reseau depuis l'interface, verifier aussi:

```bash
sudo apt install -y network-manager
```

## 4. Installation de la pile SunFounder / Picar-X

Le script `byteracer/install.sh` du depot ne clone aujourd'hui que `picar-x`. Pour une machine neuve, la pile complete decrite ci-dessous est plus fiable.

### 4.1 Installer `robot-hat`

```bash
cd ~/
git clone -b 2.5.x https://github.com/sunfounder/robot-hat.git --depth 1
cd robot-hat
sudo python3 install.py
```

### 4.2 Installer `vilib`

```bash
cd ~/
git clone https://github.com/sunfounder/vilib.git --depth 1
cd vilib
sudo python3 install.py
```

### 4.3 Installer `picar-x`

```bash
cd ~/
git clone -b 2.1.x https://github.com/sunfounder/picar-x.git --depth 1
cd picar-x
if [ -f install.py ]; then
  sudo python3 install.py
else
  sudo pip3 install ./ --break-system-packages
fi
```

### 4.4 Activer l'audio I2S fourni par SunFounder

```bash
cd ~/robot-hat
sudo bash i2samp.sh
```

Apres ce script, un redemarrage peut etre utile selon votre image Raspberry Pi OS.

## 5. Calibration du Picar-X

Ces etapes sont a faire avant d'utiliser le robot en manuel ou en autonomie.

### 5.1 Zero des servos

```bash
cd ~/picar-x/example
sudo python3 servo_zeroing.py
```

### 5.2 Calibration de la direction

```bash
cd ~/picar-x/example/calibration
sudo python3 calibration.py
```

Dans votre historique, la valeur de direction retenue etait `-3.2`. Conserver cette valeur uniquement si elle reste correcte sur votre chassis actuel.

### 5.3 Calibration des capteurs de ligne

```bash
cd ~/picar-x/example/calibration
sudo python3 grayscale_calibration.py
```

## 6. Installation de Bun et du toolchain JavaScript

### 6.1 Installer Bun

```bash
curl -fsSL https://bun.sh/install | bash
source /home/pi/.bashrc
bun --version
```

### 6.2 Rendre Bun accessible a `sudo`

Le projet lance certains builds et scripts avec `sudo`. Si `/home/pi/.bun/bin` n'est pas dans le `secure_path`, `sudo bun ...` peut echouer.

```bash
sudo visudo
```

Mettre a jour ou completer la ligne `Defaults secure_path` avec:

```text
Defaults secure_path="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/home/pi/.bun/bin"
```

### 6.3 Node.js optionnel

Le runtime principal du projet est Bun. Node.js reste toutefois utile pour certains outils ou pour reproduire l'environnement historique de setup:

```bash
sudo apt-get install -y curl
curl -fsSL https://deb.nodesource.com/setup_23.x -o nodesource_setup.sh
sudo bash nodesource_setup.sh
sudo apt-get install -y nodejs
```

Si vous ne l'utilisez pas, vous pouvez faire tourner `relaytower` et `eaglecontrol` uniquement avec Bun.

## 7. Recuperer le depot applicatif

Le robot n'a pas besoin des documents lourds, presentations, videos et anciens modeles pour fonctionner. Utiliser un sparse checkout evite de telecharger et d'ecrire ces fichiers sur la carte SD.

```bash
curl -fsSL https://raw.githubusercontent.com/Fefe-Nayz/byteracer/refs/heads/main/byteracer/scripts/install_app_sparse.sh -o install_app_sparse.sh
REPO_URL=https://github.com/Fefe-Nayz/byteracer.git \
BRANCH=main \
TARGET_DIR=/home/pi/ByteRacer \
bash install_app_sparse.sh
```

Depuis une machine neuve, le plus simple est d'utiliser le bootstrap complet:

```bash
curl -fsSL https://raw.githubusercontent.com/Fefe-Nayz/byteracer/refs/heads/main/byteracer/scripts/bootstrap_raspberry_pi.sh -o bootstrap_raspberry_pi.sh
bash bootstrap_raspberry_pi.sh
```

Variables utiles:

- `REPO_URL`: depot Git a utiliser;
- `BRANCH`: branche ou tag a installer;
- `TARGET_DIR`: dossier final, par defaut `/home/pi/ByteRacer`;
- `ROBOT_HAT_BRANCH`, `VILIB_BRANCH`, `PICARX_BRANCH`: versions SunFounder, par defaut `2.5.x`, `main`, `2.1.x`;
- `INSTALL_I2SAMP=false`: desactive l'installation automatique de l'audio I2S;
- `INSTALL_ACCESSPOPUP=false`: desactive l'installation d'AccessPopup, installee par defaut;
- `ACCESSPOPUP_SSID`, `ACCESSPOPUP_PASSWORD`, `ACCESSPOPUP_IP`: reglages du hotspot de secours.

## 8. Installation des services du projet

### 8.1 `relaytower`

```bash
cd /home/pi/ByteRacer/relaytower
bun install
bun run build
```

`RelayTower` est exporte statiquement par Next.js. En production, `bun run start` sert le dossier `relaytower/out` avec un petit serveur Bun au lieu de lancer `next start`, ce qui reduit nettement RAM, CPU et ecritures disque.

### 8.2 `eaglecontrol`

```bash
cd /home/pi/ByteRacer/eaglecontrol
bun install
```

### 8.3 `byteracer`

```bash
cd /home/pi/ByteRacer/byteracer
sudo bash ./install.sh
python3 -m pip install --break-system-packages openai SpeechRecognition sox
```

Le `install.sh` local installe seulement `picar-x`. Sur une machine neuve, il faut donc avoir deja passe les etapes `robot-hat`, `vilib` et `i2samp.sh`.

## 9. Validation rapide des prerequis Python et materiels

```bash
python3 -c "from picarx import Picarx; print('picarx ok')"
python3 -c "from vilib import Vilib; print('vilib ok')"
python3 -c "import websockets, psutil, pygame, pyaudio, numpy, PIL; print('python deps ok')"
```

Si une commande echoue, corriger les dependances avant d'essayer de lancer `main.py`.

## 10. Configuration initiale ByteRacer

Au premier lancement, `ConfigManager` cree `byteracer/config/settings.json` avec les sections:

- `sound`
- `camera`
- `safety`
- `drive`
- `modes`
- `github`
- `api`
- `ai`
- `led`

### Cle OpenAI

`GPTManager` lit la cle API dans l'ordre suivant:

1. variable d'environnement `OPENAI_API_KEY`;
2. `api.openai_api_key` dans `settings.json`.

Pour un demarrage manuel:

```bash
export OPENAI_API_KEY="votre_cle"
```

## 11. Premier demarrage manuel

Le mode manuel est le meilleur moyen de valider l'installation avant d'automatiser le boot.

### Terminal 1

```bash
cd /home/pi/ByteRacer/eaglecontrol
bun run start
```

### Terminal 2

```bash
cd /home/pi/ByteRacer/relaytower
bun run start
```

### Terminal 3

```bash
cd /home/pi/ByteRacer/byteracer
sudo python3 main.py
```

Une fois les trois services lances:

- ouvrir `http://<ip_du_robot>:3000`;
- verifier `http://<ip_du_robot>:3001/stats`;
- verifier `http://<ip_du_robot>:9000/mjpg`;
- controler que `RelayTower` passe a `connected` puis `python_status = connected`.

## 12. Demarrage automatique avec `systemd`

Le mode recommande est `systemd`, plus robuste que `screen` pour un robot qui doit redemarrer seul:

```bash
cd /home/pi/ByteRacer
bash byteracer/scripts/install_systemd_services.sh
sudo systemctl start byteracer-stack.target
```

Services installes:

- `byteracer-eaglecontrol.service`: WebSocket port `3001`;
- `byteracer-relaytower.service`: interface web statique port `3000`;
- `byteracer-python.service`: controleur Python robot;
- `byteracer-stack.target`: groupe les trois services.

Verification:

```bash
systemctl status byteracer-eaglecontrol byteracer-relaytower byteracer-python
bash /home/pi/ByteRacer/byteracer/scripts/doctor.sh
```

## 13. Fallback avec `startup.sh`

Le script racine `startup.sh` est le mode appliance du projet. Il:

1. annonce vocalement le boot;
2. attend une connexion Internet;
3. lit `github.repo_url`, `github.branch` et `github.auto_update`;
4. met a jour le depot si `auto_update = true`, en preservant `byteracer/config`;
5. reinstalle/rebuild seulement ce qui est necessaire;
6. nettoie les anciennes sessions `screen`;
7. lance `eaglecontrol`, `relaytower` et `byteracer`.

Le script est tolerant aux erreurs: une panne TTS, une absence Internet ou un echec de mise a jour ne doit pas empecher le demarrage de la version locale deja installee.

Si les services `systemd` sont installes, `startup.sh` les utilise. Sinon, il retombe sur l'ancien mode `screen`.

Lancement manuel:

```bash
cd /home/pi/ByteRacer
bash startup.sh
```

### Attention importante

Quand `github.auto_update` est a `true`, `startup.sh` peut executer un `git reset --hard origin/<branch>` dans le dossier de production. Ce mode est adapte a un robot appliance, pas a une copie de travail avec modifications locales.

## 14. Reduire l'usure de la carte SD

Le bootstrap applique ces reglages:

- logs applicatifs dans `/tmp/byteracer/logs` par defaut;
- `journald` en mode volatile avec taille limitee;
- `/tmp` en `tmpfs`;
- `noatime` sur la racine si possible;
- `zram-tools` pour eviter le swap classique sur SD.

Le fichier Python garde seulement quelques logs courts en rotation. Pour rendre les logs persistants temporairement:

```bash
export BYTERACER_LOG_DIR=/home/pi/ByteRacer/byteracer/logs
export BYTERACER_FILE_LOG_LEVEL=INFO
```

## 15. Activation au boot via `crontab`

Pour reproduire le setup de production historique:

```bash
crontab -e
```

Ajouter la ligne suivante:

```bash
@reboot export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/home/pi/.bun/bin" && /home/pi/ByteRacer/startup.sh >> /home/pi/startup.log 2>&1
```

Le diagnostic rapide se lance avec:

```bash
bash /home/pi/ByteRacer/byteracer/scripts/doctor.sh
```

Eviter `sudo chmod -R 777 /home/pi/ByteRacer/`. Si des permissions bloquent, corriger plutot le proprietaire du dossier (`pi`) et les permissions des scripts.

## 16. Installation du mode point d'acces / AccessPopup

Les fonctions reseau du projet s'appuient sur `accesspopup` pour basculer le robot en point d'acces et exposer un portail de configuration.

```bash
cd /home/pi
curl "https://www.raspberryconnect.com/images/scripts/AccessPopup.tar.gz" -o AccessPopup.tar.gz
tar -xvf ./AccessPopup.tar.gz
cd AccessPopup
sudo ./installconfig.sh
```

Pendant l'installation:

- choisir l'option `install`;
- definir le nom du point d'acces;
- definir le mot de passe du point d'acces.

## 17. Check-list de verification finale

Verifier les points suivants:

- `screen -ls` affiche `eaglecontrol`, `relaytower` et `byteracer` si vous utilisez `startup.sh`;
- `http://<ip_du_robot>:3000` sert l'interface;
- `http://<ip_du_robot>:3001/stats` affiche au moins un client `car` quand Python est lance;
- `http://<ip_du_robot>:9000/mjpg` renvoie un flux MJPEG;
- la manette remonte dans l'onglet `Gamepad`;
- les donnees capteurs et batterie se mettent a jour;
- la camera repond et peut etre redemarree depuis l'interface;
- le robot parle via TTS et joue les sons;
- les commandes GPT fonctionnent si la cle OpenAI est configuree.

## 18. Depannage rapide

### Le robot ne se connecte pas a EagleControl

- verifier que `eaglecontrol` tourne sur le port `3001`;
- verifier que `ByteRacer` peut joindre `ws://127.0.0.1:3001/ws`;
- verifier `http://<host>:3001/stats` pour confirmer la presence d'un client `car`.

### Le flux camera ne s'affiche pas

- verifier `http://<host>:9000/mjpg` directement dans un navigateur;
- verifier l'installation de `Picamera2` et `vilib`;
- verifier que la camera est bien detectee par le Raspberry Pi;
- utiliser `restart_camera_feed` depuis l'interface si le flux est gele.

### Le TTS ne parle pas

- verifier `pico2wave`;
- verifier `sox`;
- verifier l'installation du script `i2samp.sh`;
- verifier la sortie audio et les volumes `sound` / `tts`.

### Les fonctions reseau ne marchent pas

- verifier `nmcli`;
- verifier la presence de `/usr/local/bin/accesspopup` et `/etc/accesspopup.conf`;
- verifier que `NetworkManager` tourne bien;
- verifier les permissions `sudo` pour les commandes reseau.

### GPT, l'audio ou la reconnaissance vocale echouent

- verifier `OPENAI_API_KEY` ou `api.openai_api_key`;
- verifier `openai`, `SpeechRecognition`, `sox` et `pyaudio`;
- verifier la presence du microphone si vous utilisez les modes conversationnels;
- verifier la connectivite Internet du robot avant d'essayer un appel OpenAI.

## 19. Resume des commandes utiles

```bash
# preparation systeme
sudo raspi-config
sudo apt update && sudo apt upgrade -y && sudo apt autoremove -y

# pile SunFounder
cd ~/ && git clone -b v2.0 https://github.com/sunfounder/robot-hat.git
cd ~/ && git clone -b picamera2 https://github.com/sunfounder/vilib.git
cd ~/ && git clone -b v2.0 https://github.com/sunfounder/picar-x.git --depth 1
cd ~/picar-x && sudo bash i2samp.sh

# calibrations
cd ~/picar-x/example && sudo python3 servo_zeroing.py
cd ~/picar-x/example/calibration && sudo python3 calibration.py
cd ~/picar-x/example/calibration && sudo python3 grayscale_calibration.py

# installation projet
cd /home/pi && git clone -b main https://github.com/Fefe-Nayz/byteracer.git ByteRacer
cd /home/pi/ByteRacer/relaytower && bun install && bun run build
cd /home/pi/ByteRacer/eaglecontrol && bun install
cd /home/pi/ByteRacer/byteracer && sudo bash ./install.sh
python3 -m pip install --break-system-packages openai SpeechRecognition sox

# demarrage manuel
cd /home/pi/ByteRacer/eaglecontrol && bun run start
cd /home/pi/ByteRacer/relaytower && bun run start
cd /home/pi/ByteRacer/byteracer && sudo python3 main.py
```
