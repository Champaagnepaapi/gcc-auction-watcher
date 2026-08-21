# Robot KB local — Mac mini

Cette lane remplace le stockage Neon par un PostgreSQL **local uniquement** sur le Mac.

## Contrat

- runtime Robot KB réutilisé exactement depuis le P3 validé `1d06fe33b6fc640657255e15a8d17251aa02b6ce` ;
- PostgreSQL écoute/utilise `127.0.0.1`, aucune exposition Internet requise ;
- aucune clé/API/password n'est écrite dans le dépôt ;
- l'URL Neon n'est demandée qu'en saisie masquée pendant la migration et n'est pas persistée ;
- collectors = GET/read-only côté marchés ; aucune transaction, achat, bid ou checkout ;
- SOLD seulement si la source prouve explicitement la vente ; ask/live auction/disparition ne deviennent jamais SOLD.

## Installation

Après avoir récupéré la branche/main contenant cette phase, double-cliquer :

`Installer Robot KB Local.command`

L'installateur :

1. installe Homebrew si nécessaire, PostgreSQL 16 et Python 3.12 ;
2. extrait le runtime P3 validé dans `~/Library/Application Support/RobotPokemonKB/runtime-p3` ;
3. crée un venv local ;
4. exige la migration Neon avant d'activer les collectors sur une installation neuve ;
5. installe trois LaunchAgents : fixed/auction à `:32`, SOLD à `:17` et `:47`, backup à `03:10` ;
6. lance un rattrapage initial puis un health-check.

## Migration Neon

`Migrer Robot KB Neon vers Mac.command`

- demande la DATABASE URL Neon en saisie masquée ;
- fait un `pg_dump` custom via le helper secret-safe existant ;
- restaure dans `robot_pokemon_kb` local ;
- compare les fingerprints/row counts source ↔ local ;
- conserve le dump initial dans `~/Library/Application Support/RobotPokemonKB/migration-backup`.

Si Neon refuse les requêtes à cause du quota, **ne pas supprimer le projet Neon** : attendre son retour en lecture ou effectuer un upgrade temporaire uniquement pour exporter. Les collectors locaux ne sont pas activés sur une base vide par défaut.

## État

Double-cliquer `Etat Robot KB Local.command`.

Données : `~/Library/Application Support/RobotPokemonKB/`

Logs : `~/Library/Logs/RobotPokemonKB/`

Backups : 7 derniers dumps complets conservés localement.
