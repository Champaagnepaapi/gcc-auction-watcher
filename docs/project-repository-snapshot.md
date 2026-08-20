# Robot Pokémon / GCC Auction Watcher — snapshot topologique du dépôt

Snapshot vérifié le **20 août 2026** après le merge #151.

## Autorité live vérifiée

```text
Repository                    Champaagnepaapi/gcc-auction-watcher
Default branch                main
main HEAD                     c9539ca521f69b43b3d93e621fb21447a69f3fe7
Last runtime merge            #151 Global schedule run registry
main protected                false
Open pull requests            17 avant ouverture de la branche docs courante
Current workflow YAML files   16
True GitHub issues            4
```

Le HEAD ci-dessus est le dernier runtime vérifié avant la branche docs de fermeture ; un merge docs-only le fera naturellement avancer.

Le nombre total de branches distantes n'a pas été ré-audité exhaustivement. Le dernier audit exhaustif connu comptait 158 le 18 août, mais plusieurs branches ont été créées depuis : ne pas présenter 158 comme nombre courant.

## Global production

```text
#139   réintégration Multi-Vault
#140   confirmation économique externe
#142   bridge exact provider absorbé par #140
#145   notification runtime
#146   activation réelle
#147   marketplace-first discovery
#148   cutover production vers marketplace-first
#151   run registry autonome vers issue #150
```

`v4-global-notify.yml` reste l'unique cron Global. #151 n'ajoute aucun workflow/schedule ; il ajoute seulement un finalizer schedule-only qui écrit des métadonnées minimales dans l'issue #150.

Activation : marker `.github/global-notify-activation=true`, repo var true supportée, repo var false kill switch prioritaire, manual dispatch dry-run.

## Validation #151

```text
head                    a424fb62cb5e0553929847d3b973411a8b61a561
merge                   c9539ca521f69b43b3d93e621fb21447a69f3fe7
run                     32410224171 SUCCESS
validate/live jobs      96558656377 / 96558728745 SUCCESS
Global                  203/203 PASS
V4 multimarket           51/51 PASS
compile/YAML/diff       PASS
live read-only          SUCCESS
inventory               1186
selected/pending        10 / 1176
transactions            false
artifact                9421951722
```

Le premier vrai commentaire #150 produit par un `schedule` post-#151 reste à observer explicitement ; ne pas le revendiquer sans commentaire/run ID/logs.

## PR importantes

Open PR surface reste gouvernée par `docs/project-open-pr-inventory.md`. Principales règles :

- #8 : **OPEN / DRAFT / V5 EXPERIMENTAL / NON MERGED** ;
- #54 : stale/superseded ;
- #87 : décision produit V4 séparée ;
- #92/#96 : V5 child/shadow/deferred ;
- #106/#107 : anciens PPT/Japan shadows ;
- #108/#109/#110/#113/#114/#115/#138 : absorbées par #139 ;
- #126 : superseded par #127→#135 ;
- #141 : diagnostic superseded par #142/#140.

#146/#147/#148/#151 sont mergées.

## Workflows

16 YAML dans le tree :

- `watcher.yml` : V4 Main Scanner, cadence externe ;
- `v4-final-auction-check.yml` : Fast Lane, cadence externe ;
- `v4-global-notify.yml` : unique Global schedule `41 * * * *`, marketplace-first + registry #150 ;
- `v4-global-live-shadow.yml` : manuel/read-only ;
- `v4-global-market-offline-validation.yml` : CI Global ;
- Robot KB : workflows séparés ;
- V5 lives : manuels/expérimentaux ;
- `v5-gcc-catalog-refresh.yml` : support legacy actuel.

## Branches

Branches #147/#148/#151 conservées comme provenance. Aucune suppression implicite. Toute suppression exige audit d'atteignabilité/supersession + autorisation destructive explicite.

## Issues

Audit live : **4 vraies issues** hors PR :

- #1 : `ACTIVE_V4_RUN_REGISTRY` ;
- #28 : historique/completed ;
- #58 : planning Robot KB stale/superseded-by-delivered-stack ;
- #150 : `ACTIVE_GLOBAL_RUN_REGISTRY`.

#1 et #150 sont volontairement séparées. Ne pas fermer/réécrire une issue de housekeeping sans autorisation explicite.

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