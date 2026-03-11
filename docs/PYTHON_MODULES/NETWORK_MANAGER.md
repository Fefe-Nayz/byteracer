# `network_manager.py`

## Role

`NetworkManager` encapsule les operations reseau du robot: scan Wi-Fi, connexion, changement de mode, mise a jour du point d'acces et lecture du statut.

## Responsabilites

- lancer des commandes shell reseau de maniere encadree;
- scanner les reseaux disponibles;
- connecter ou enregistrer un SSID;
- supprimer un reseau memorise;
- basculer entre mode Wi-Fi classique et point d'acces;
- mettre a jour les parametres AP;
- exposer IP, connexion courante et acces Internet.

## API principale

- `scan_wifi_networks()`;
- `connect_to_wifi(ssid, password)`;
- `add_or_update_wifi(ssid, password)`;
- `remove_wifi_network(ssid)`;
- `switch_wifi_mode(mode)`;
- `update_ap_settings(ssid, password)`;
- `get_saved_wifi_networks()`;
- `get_connection_status()`;
- `restart_networking()`.

## Dependances externes

- `nmcli` / `NetworkManager`;
- `accesspopup` pour le portail point d'acces;
- commandes shell appelees via `_run_command(...)`.

## Interactions

- `ByteRacer.execute_network_action()` route les demandes du front ici;
- `ConfigManager` peut stocker les reseaux connus;
- `NetworkSettings.tsx` affiche les resultats des scans et des changements de mode.

## Point d'attention

Ce module depend fortement de l'image systeme. Une installation doc complete doit donc verifier la presence de `nmcli` et d'`accesspopup`, sinon plusieurs boutons de l'interface n'auront aucun effet utile.
