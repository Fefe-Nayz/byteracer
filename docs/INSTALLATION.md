# Installation Du Projet

## Objectif

Cette documentation decrit l'installation du projet dans son mode cible: un Raspberry Pi hebergeant les trois services suivants:

- `ByteRacer` sur Python;
- `EagleControl` sur Bun;
- `RelayTower` sur Next.js.

Elle couvre aussi un mode manuel utile pour le developpement ou le diagnostic.

## 1. Prerequis

### Materiel cible

- un Raspberry Pi compatible avec la pile camera et les bibliotheques SunFounder;
- un robot SunFounder Picar-X;
- une camera compatible `Picamera2`;
- facultatif: microphone USB pour les fonctions audio entrantes et conversationnelles.

### Systeme d'exploitation recommande

- Raspberry Pi OS / Debian avec acces `sudo`;
- `NetworkManager` et `nmcli` si les fonctions Wi-Fi/AP doivent etre actives.

### Outils systeme attendus par le code

Le code et les scripts de demarrage s'appuient sur les outils suivants:

- `git`
- `curl`
- `jq`
- `screen`
- `sox`
- `pico2wave` via `libttspico-utils`
- `nmcli`
- `accesspopup` pour la bascule en mode point d'acces
- `python3`
- `bun`

Exemple d'installation de base sur Debian/Raspberry Pi OS:

```bash
sudo apt update
sudo apt install -y \
  git curl jq screen sox libsox-fmt-all libttspico-utils \
  python3 python3-pip python3-dev \
  python3-websockets python3-psutil python3-pygame \
  python3-pyaudio python3-numpy python3-pil
```

## 2. Recuperer le depot

En production, le script `startup.sh` suppose un emplacement final dans `/home/pi/ByteRacer`.

```bash
cd /home/pi
git clone https://github.com/nayzflux/byteracer.git ByteRacer
cd ByteRacer
```

Si vous utilisez une branche specifique, adaptez votre clone. Le boot script utilise par defaut la branche `working-2` si aucune configuration n'est encore presente.

## 3. Installer Bun et les services JavaScript

### Installer Bun

```bash
curl -fsSL https://bun.sh/install | bash
source ~/.bashrc
bun --version
```

### Installer `RelayTower`

```bash
cd /home/pi/ByteRacer/relaytower
bun install
bun run build
```

### Installer `EagleControl`

```bash
cd /home/pi/ByteRacer/eaglecontrol
bun install
```

## 4. Installer la pile Python et materielle

### Installation minimale pilotee par le depot

Le depot fournit un script `byteracer/install.sh` qui installe la bibliotheque `picarx` depuis le depot officiel SunFounder:

```bash
cd /home/pi/ByteRacer/byteracer
sudo bash install.sh
```

### Installation des bibliotheques locales SunFounder embarquees dans le depot

Si votre image n'integre pas deja la pile SunFounder complete, les variantes embarquees dans le depot peuvent etre installees manuellement.

#### `picarx`

```bash
cd /home/pi/ByteRacer/byteracer/modules/picarx-custom
sudo python3 setup.py install
```

#### `vilib`

```bash
cd /home/pi/ByteRacer/byteracer/modules/vilib-custom
sudo python3 install.py
```

### Dependances Python utilisees par le code

Le code Python utilise au minimum les bibliotheques suivantes:

- `websockets`
- `psutil`
- `pygame`
- `pyaudio`
- `numpy`
- `Pillow`
- `openai`
- `SpeechRecognition`
- `sox`

Le fichier `byteracer/requirements.txt` ne reference actuellement que `websockets`. Pour un environnement neuf, il faut donc installer aussi les dependances additionnelles utilisees par le code.

Exemple d'installation complementaire:

```bash
python3 -m pip install --break-system-packages \
  openai SpeechRecognition sox
```

Si vous utilisez un environnement Python different, adaptez la commande et le mode de lancement de `main.py` en consequence.

### Validation rapide de la pile Python

```bash
python3 -c "from picarx import Picarx; print('picarx ok')"
python3 -c "from vilib import Vilib; print('vilib ok')"
python3 -c "import websockets, psutil, pygame, pyaudio, numpy, PIL; print('python deps ok')"
```

## 5. Configuration initiale

### Fichier de configuration genere par le robot

Au premier demarrage, `ConfigManager` cree le fichier:

- `byteracer/config/settings.json`

Ce fichier contient les sections:

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

1. variable d'environnement `OPENAI_API_KEY`
2. `api.openai_api_key` dans `byteracer/config/settings.json`

Pour un demarrage manuel:

```bash
export OPENAI_API_KEY="votre_cle"
```

### Parametres Git du mode appliance

`startup.sh` lit ces valeurs dans `settings.json` si elles existent:

- `github.repo_url`
- `github.branch`
- `github.auto_update`

## 6. Demarrage automatique avec `startup.sh`

Le script racine `startup.sh` est le mode de demarrage production. Il execute la sequence suivante:

1. annonce vocale du boot;
2. verification de la connexion Internet;
3. mise a jour ou clonage du depot dans `/home/pi/ByteRacer`;
4. installation/reinstallation des dependances;
5. build du front `RelayTower`;
6. lancement de `eaglecontrol`, `relaytower` et `byteracer` dans des sessions `screen`.

Lancement:

```bash
cd /home/pi/ByteRacer
bash startup.sh
```

### Attention importante

Quand `github.auto_update` est a `true`, `startup.sh` peut executer un `git reset --hard origin/<branch>` dans le dossier de production. Ce mode est adapte a un robot appliance, pas a une copie de travail avec modifications locales.

## 7. Demarrage manuel service par service

Le demarrage manuel est utile pour le developpement et le debug.

### Mode production manuel

Terminal 1:

```bash
cd /home/pi/ByteRacer/eaglecontrol
bun run start
```

Terminal 2:

```bash
cd /home/pi/ByteRacer/relaytower
bun run start
```

Terminal 3:

```bash
cd /home/pi/ByteRacer/byteracer
sudo python3 main.py
```

### Mode developpement partiel

Pour travailler sur l'interface et le bus WebSocket sans build de production:

```bash
cd /home/pi/ByteRacer/eaglecontrol
bun run dev
```

```bash
cd /home/pi/ByteRacer/relaytower
bun run dev
```

`ByteRacer` reste toutefois dependant du materiel et de la pile Python Raspberry Pi.

## 8. Verification apres installation

Verifiez les points suivants:

- l'interface est accessible sur `http://<ip_du_robot>:3000`;
- le serveur WebSocket repond sur `ws://<ip_du_robot>:3001/ws`;
- les statistiques de connexion sont visibles sur `http://<ip_du_robot>:3001/stats`;
- le flux camera est accessible sur `http://<ip_du_robot>:9000/mjpg`;
- les logs apparaissent dans `byteracer/logs/`;
- `RelayTower` passe a l'etat `connected` puis `python_status = connected`.

Si vous utilisez `startup.sh`, vous pouvez aussi verifier les sessions `screen`:

```bash
screen -ls
```

## 9. Depannage rapide

### L'interface indique que Python est deconnecte

- verifier que `ByteRacer` tourne bien;
- verifier que `ByteRacer` peut joindre `ws://127.0.0.1:3001/ws`;
- verifier qu'au moins un client `car` apparait dans `http://<host>:3001/stats`.

### Le flux camera ne s'affiche pas

- verifier `http://<host>:9000/mjpg` directement dans un navigateur;
- verifier l'installation de `Picamera2` et `vilib`;
- utiliser `restart_camera_feed` depuis l'interface si le flux est gele.

### Le TTS ne parle pas

- verifier `pico2wave`;
- verifier `sox`;
- verifier la sortie audio et le volume `sound` / `tts` dans les reglages.

### Les fonctions reseau ne marchent pas

- verifier `nmcli`;
- verifier la presence de `/usr/bin/accesspopup`;
- verifier que l'utilisateur courant peut executer les commandes reseau attendues.

### GPT ou la reconnaissance vocale echouent

- verifier `OPENAI_API_KEY` ou `api.openai_api_key`;
- verifier l'installation de `openai`, `SpeechRecognition` et `sox`;
- verifier la presence du microphone si vous utilisez les modes conversationnels.

## 10. Resume des commandes utiles

```bash
# installation JS
cd relaytower && bun install && bun run build
cd ../eaglecontrol && bun install

# installation Python/materiel
cd ../byteracer && sudo bash install.sh
python3 -m pip install --break-system-packages openai SpeechRecognition sox

# demarrage production
cd /home/pi/ByteRacer && bash startup.sh

# demarrage manuel
cd /home/pi/ByteRacer/eaglecontrol && bun run start
cd /home/pi/ByteRacer/relaytower && bun run start
cd /home/pi/ByteRacer/byteracer && sudo python3 main.py
```
