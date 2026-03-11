# `gpt/preset_actions.py`

## Role

`preset_actions.py` contient des sequences motrices predefinies reutilisables par `GPTManager` pour donner au robot des comportements expressifs.

## Actions disponibles

- `wave_hands`
- `resist`
- `act_cute`
- `rub_hands`
- `think`
- `keep_think`
- `shake_head`
- `nod`
- `depressed`
- `twist_body`
- `celebrate`

## Utilisation

Ces fonctions sont appelees depuis `execute_predefined_function()` dans `GPTManager`. Elles permettent:

- d'eviter qu'un comportement gestuel simple passe par un script Python genere;
- de garder des motions expressives testees et partageables;
- de rendre les demos ChatGPT plus lisibles pour l'utilisateur final.

## Point d'attention

Ces motions utilisent les memes primitives servo/moteur que le reste du robot. Elles doivent donc rester compatibles avec les limites mecaniques du chassis et avec les etats de securite appliques par `SensorManager`.
