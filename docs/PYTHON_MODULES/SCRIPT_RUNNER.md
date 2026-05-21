# `script_runner.py`

## Role

`script_runner.py` execute les scripts Python dynamiques produits par `GPTManager` dans un environnement isole et encadre.

## Responsabilites

- reconstruire un environnement limite autour du script utilisateur;
- injecter seulement les primitives autorisees;
- capter les commandes audio / TTS demandees par le script;
- supporter l'annulation de script;
- renvoyer un resultat structure ou une erreur a `GPTManager`;
- proposer une verification statique minimale via `check_script_for_issues(...)`.

## Fonctions principales

- `_build_script_with_environment(script_code)`;
- `run_script_in_isolated_environment(...)`;
- `check_script_for_issues(script_code)`.

## Primitives exposees au script

Le script n'a pas acces au projet entier. Il travaille avec un sous-ensemble tel que:

- `px` pour le mouvement;
- `get_camera_image`;
- `tts`;
- `sound`;
- le gestionnaire LED;
- une reference au `gpt_manager` dans un cadre controle.

## Interactions

- appelle par `GPTManager` quand l'action retournee est `python_script`;
- s'appuie sur `asyncio`, des queues et un environnement reconstruit;
- partage les memes primitives materiel que le reste du systeme, mais pas les memes droits d'acces.

## Point fort

Ce module est l'un des garde-fous les plus importants de l'integration ChatGPT. Il permet de garder une grande souplesse de demo sans laisser une generation de code libre s'executer dans le meme contexte que tout le serveur.
