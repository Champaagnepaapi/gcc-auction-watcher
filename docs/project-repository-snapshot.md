# Robot Pokémon / GCC Auction Watcher — snapshot topologique du dépôt

Snapshot vérifié le **21 août 2026** après le merge #154.

## Autorité live vérifiée

```text
Repository                    Champaagnepaapi/gcc-auction-watcher
Default branch                main
main HEAD                     c3e3da39b79eb71cfdfc864bb865c4a4e7154e0c
Last runtime merge            #154 TCGdex detailed variants
main protected                false
Open pull requests            17 avant ouverture de la branche docs courante
Current workflow YAML files   16
True GitHub issues            4
```

Le HEAD ci-dessus est le runtime vérifié avant la fermeture docs ; un merge docs-only le fera avancer.

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
```

`v4-global-notify.yml` reste l'unique cron Global. #153 modifie uniquement le trigger schedule du workflow existant ; #154 ne crée aucun workflow.

## Preuves production / validation

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

Le premier schedule contenant explicitement #154 n'avait pas encore été observé dans #150 au moment de ce snapshot ; ne pas le fabriquer.

## TCGdex exact identity

#154 ajoute `variants_detailed` après macro identité exacte : finish/edition/shadow/special foil supportés, plusieurs/malformed/inconnus/contradictoires fail-closed. Le source-pinned japonais reste prioritaire et le `pricing` TCGdex détaillé n'est pas une source de fair value slab.

## PR importantes

Open PR surface : **17** résultats live après merge #154. Principales règles :

- #8 : **OPEN / DRAFT / V5 EXPERIMENTAL / NON MERGED** ;
- #54 : stale/superseded ;
- #87 : décision produit V4 séparée ;
- #92/#96 : V5 child/shadow/deferred ;
- #106/#107 : anciens PPT/Japan shadows ;
- #108/#109/#110/#113/#114/#115/#138 : absorbées par #139 ;
- #126 : superseded par #127→#135 ;
- #141 : diagnostic superseded par #142/#140.

#153/#154 sont mergées et ne sont plus dans la surface ouverte.

## Workflows

16 YAML dans le tree :

- `watcher.yml` : V4 Main Scanner, cadence externe ;
- `v4-final-auction-check.yml` : Fast Lane, cadence externe ;
- `v4-global-notify.yml` : unique Global schedule `1,11,21,31,41,51 * * * *`, marketplace-first + registry #150 ;
- `v4-global-live-shadow.yml` : manuel/read-only ;
- `v4-global-market-offline-validation.yml` : CI Global ;
- Robot KB : workflows séparés ;
- V5 lives : manuels/expérimentaux ;
- `v5-gcc-catalog-refresh.yml` : support legacy actuel.

## Branches

Branches #147/#148/#151/#153/#154 conservées comme provenance. Aucune suppression implicite. Toute suppression exige audit d'atteignabilité/supersession + autorisation destructive explicite.

## Issues

Audit live : **4 vraies issues** hors PR :

- #1 : `ACTIVE_V4_RUN_REGISTRY` ;
- #28 : historique/completed ;
- #58 : planning Robot KB stale/superseded-by-delivered-stack ;
- #150 : `ACTIVE_GLOBAL_RUN_REGISTRY`, désormais prouvé par de vrais commentaires schedule.

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
- Robot KB/Neon séparé ;
- Cardova fail-closed sans session sûre.