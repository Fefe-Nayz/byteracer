# `log_manager.py`

## Role

`LogManager` centralise les logs Python, les ecrit sur disque et peut les diffuser en temps reel sur le WebSocket.

## Sous-composants

- `ColoredFormatter`: rendu console colore;
- `WebSocketLogHandler`: pont asynchrone logger -> WebSocket;
- `LogManager`: cycle de vie, rotation et lecture des fichiers.

## Responsabilites

- configurer les handlers console, fichier et WebSocket;
- creer le repertoire de logs;
- surveiller la taille des fichiers;
- supprimer les anciens logs au dela des limites configurees;
- exposer `get_log_list()` et `get_log_content()` pour le debug.

## API principale

- `set_websocket(websocket)`;
- `start()` / `stop()`;
- `get_log_list()`;
- `get_log_content(log_name, max_lines)`.

## Interactions

- `ByteRacer` lui donne le WebSocket courant;
- `RelayTower` consomme les `log_message` via `LogViewer.tsx`;
- toutes les autres classes du service Python beneficient indirectement de cette infrastructure.

## Point fort

La presence d'un handler WebSocket simplifie beaucoup le diagnostic a distance: le front devient une console de supervision et pas seulement une telecommande.
