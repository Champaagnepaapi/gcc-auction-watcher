# Robot Pokémon / GCC Auction Watcher — snapshot topologique du dépôt

Snapshot vérifié le **21 août 2026** pendant la préparation Robot KB #157.

## Autorité live vérifiée

```text
Repository                    Champaagnepaapi/gcc-auction-watcher
Default branch                main
main HEAD                     2738be454fe0323e7f1cf8d66309fa5bbff6964c
Last runtime merge            #154 / c3e3da39b79eb71cfdfc864bb865c4a4e7154e0c
main protected                false
Open pull requests            19 (#156 + #157 incluses)
Current main workflow YAML    16
Proposed after #157           17 (validation Mac uniquement)
True GitHub issues            4
```

Le HEAD `2738be...` est le merge docs-only #155 ; le runtime commercial reste #154.

Le nombre total de branches distantes n'a pas été ré-audité exhaustivement. Le dernier audit exhaustif connu comptait 158 le 18 août, mais plusieurs branches ont été créées depuis : ne pas présenter 158 comme nombre courant.

## Global production

```text
#139   réintégration Multi-Vault
#140   confirmation économique externe
#142   bridge exact provider absorbé par #140
#145   notification runtime
#146   activation réelle
#147   marketplace-first discovery
#148   cutover production marketplace-first
#151   run registry autonome vers issue #150
#153   cadence du même Global workflow à toutes les 10 min
#154   TCGdex variants_detailed dans le gate microvariante exact
#155   docs-only fermeture #154
```

`v4-global-notify.yml` reste l'unique cron Global. PR #156 est une ligne de scale séparée et reste ouverte ; elle n'est pas production tant qu'elle n'est pas mergée.

## Robot KB migration stockage

PR #157 / `feat/robot-kb-local-postgres-mac-20260821` prépare PostgreSQL local Mac en réutilisant P3 `1d06fe33b6fc640657255e15a8d17251aa02b6ce`.

État : `PREPARED_LOCAL_MAC / NEON_CUTOVER_PENDING`.

- nouveaux scripts sous `mac/robot-kb-local/` ;
- DB cible loopback `127.0.0.1/robot_pokemon_kb` ;
- dump/restore + fingerprint source/local avant activation ;
- LaunchAgents locaux fixed `:32`, SOLD `:17/:47`, backup `03:10` ;
- Neon cloud writers **encore actifs** dans #157 ;
- cutover/suppression Neon interdits avant preuve `MIGRATION_VERIFIED` + health-check local.

## Preuves production / validation #154

Registre #150 prouvé : run `32411433425`, schedule, activation true, mode `GLOBAL_MARKETPLACE_NOTIFICATION_ACTIVE`, success, 0 sent, transactions false.

Cadence #153 prouvée : run `32443663511` sur `e79e939c...`, success, activation true, inventory 1196, selected 10, pending 1137, 0 sent, transactions false.

Validation #154 :

```text
head                    bb21aeb118c66a3da5df6bc949ce64d23bab2c1b
merge                   c3e3da39b79eb71cfdfc864bb865c4a4e7154e0c
run                     32444255909 SUCCESS
validate/live jobs      96660771327 / 96660823079 SUCCESS
Global                  221/221 PASS
V4 multimarket           51/51 PASS
full V4 validation      SUCCESS
live read-only          SUCCESS
inventory               1196
selected/pending        10 / 1186
transactions            false
artifact                9433579221
```

## TCGdex exact identity

#154 ajoute `variants_detailed` après macro identité exacte : finish/edition/shadow/special foil supportés, plusieurs/malformed/inconnus/contradictoires fail-closed. Le source-pinned japonais reste prioritaire et le `pricing` TCGdex détaillé n'est pas une source de fair value slab.

## PR importantes

Open PR surface : **19** résultats live au snapshot. Principales règles :

- #8 : **OPEN / DRAFT / V5 EXPERIMENTAL / NON MERGED** ;
- #54 : stale/superseded ;
- #87 : décision produit V4 séparée ;
- #92/#96 : V5 child/shadow/deferred ;
- #106/#107 : anciens PPT/Japan shadows ;
- #108/#109/#110/#113/#114/#115/#138 : absorbées par #139 ;
- #126 : superseded par #127→#135 ;
- #141 : diagnostic superseded par #142/#140 ;
- #156 : Global scale/provider-gap, ouverte et séparée ;
- #157 : Robot KB local Mac preparation, ouverte ; cutover Neon pending.

## Workflows

`main` contient encore 16 YAML. #157 propose un 17e workflow : `robot-kb-local-postgres-validation.yml`, CI/manual seulement.

- `watcher.yml` : V4 Main Scanner, cadence externe ;
- `v4-final-auction-check.yml` : Fast Lane, cadence externe ;
- `v4-global-notify.yml` : unique Global schedule `1,11,21,31,41,51 * * * *`, marketplace-first + registry #150 ;
- `v4-global-live-shadow.yml` : manuel/read-only ;
- `v4-global-market-offline-validation.yml` : CI Global ;
- Robot KB Neon : `robot-kb-cloud-shadow.yml`, `robot-kb-sold-shadow.yml`, `v4-kb-shadow-ingest.yml` encore actifs avant cutover ;
- Robot KB Mac : validation #157 + LaunchAgents locaux hors GitHub Actions ;
- V5 lives : manuels/expérimentaux ;
- `v5-gcc-catalog-refresh.yml` : support legacy actuel.

## Branches

Branches #147/#148/#151/#153/#154 conservées comme provenance. #156 et #157 sont actives et indépendantes. Aucune suppression implicite. Toute suppression exige audit d'atteignabilité/supersession + autorisation destructive explicite.

## Issues

Audit live : **4 vraies issues** hors PR :

- #1 : `ACTIVE_V4_RUN_REGISTRY` ;
- #28 : historique/completed ;
- #58 : planning Robot KB stale/superseded-by-delivered-stack ;
- #150 : `ACTIVE_GLOBAL_RUN_REGISTRY`.

#1 et #150 restent volontairement séparées.

## Documents d'autorité

- `README.md` : handoff canonique ;
- `docs/project-current-phase.md` : phase courante ;
- `docs/project-capability-ledger.md` : capacités/supersessions ;
- `docs/project-open-pr-inventory.md` : PR ouvertes ;
- `docs/project-workflow-inventory.md` : workflows ;
- `docs/project-branch-inventory.md` : branches ;
- `docs/project-issue-inventory.md` : issues.

## Invariants

- V4/main canonique ;
- PR #8 jamais mergée sans autorisation explicite ;
- ASK/enchère live/disparition != SOLD ;
- aucun fuzzy comme preuve exacte ;
- aucun achat, bid, checkout ou paiement automatique ;
- Robot KB séparé de V4/V5 ;
- Neon ne peut être coupé qu'après migration Mac vérifiée ;
- Cardova fail-closed sans session sûre.