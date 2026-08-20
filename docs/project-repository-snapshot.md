# Robot Pokémon / GCC Auction Watcher — snapshot topologique du dépôt

Snapshot vérifié le **20 août 2026** après le merge marketplace-first #148.

## Autorité live vérifiée

```text
Repository                    Champaagnepaapi/gcc-auction-watcher
Default branch                main
main HEAD                     ea9a69b375434031c935de8d25fcc12acd1a1c93
Last runtime merge            #148 marketplace-first cutover
main protected                false
Open pull requests            17
Current workflow YAML files   16
```

Le HEAD ci-dessus est le dernier runtime vérifié avant la branche docs de fermeture ; un merge docs-only le fera naturellement avancer.

Le nombre distant total de branches n'a **pas** été ré-audité exhaustivement pendant cette fermeture. Le dernier audit exhaustif connu comptait 158 branches le 18 août, mais plusieurs branches ont été créées depuis : ne pas présenter 158 comme nombre courant.

## Global production

```text
#139   réintégration Multi-Vault
#140   confirmation économique externe
#142   bridge exact provider absorbé par #140
#145   notification runtime
#146   activation réelle
#147   marketplace-first discovery
#148   cutover du workflow production vers marketplace-first
```

`v4-global-notify.yml` reste l'unique cron Global et exécute désormais le runner marketplace-first. Aucun second schedule n'a été créé.

Activation : marker `.github/global-notify-activation=true`, repo var `true` supportée, repo var `false` kill switch prioritaire, manual dispatch dry-run.

## Validation #148

```text
head                    9ff96e9cd9124944e50bb55e990289f5fd07492f
merge                   ea9a69b375434031c935de8d25fcc12acd1a1c93
run                     32398465774 SUCCESS
Global                  202/202 PASS
V4 multimarket           51/51 PASS
compile/YAML/diff       PASS
live read-only          SUCCESS
inventory               1184
selected/pending        10 / 1174
transactions            false
```

Le premier vrai run `schedule` post-#148 n'a pas encore été observé explicitement dans cette fermeture ; ne pas le revendiquer sans ID/logs.

## PR importantes

Open PR search live retourne 17 PRs. Les principales règles :

- #8 : **OPEN / DRAFT / V5 EXPERIMENTAL / NON MERGED** ;
- #54 : stale/superseded ;
- #87 : décision produit V4 séparée/non déployée ;
- #92/#96 : V5 child/shadow/deferred ;
- #106/#107 : anciens PPT/Japan shadows ;
- #108/#109/#110/#113/#114/#115/#138 : stack historique absorbé par #139 ;
- #126 : superseded par #127→#135 ;
- #141 : diagnostic superseded par #142/#140.

#146/#147/#148 sont mergées et ne figurent plus dans la surface ouverte.

Voir `docs/project-open-pr-inventory.md` pour le détail.

## Workflows

Le tree courant contient 16 YAML. Principales lanes :

- `watcher.yml` : V4 Main Scanner, cadence externe ;
- `v4-final-auction-check.yml` : Fast Lane, cadence externe ;
- `v4-global-notify.yml` : unique Global schedule `41 * * * *`, marketplace-first ;
- `v4-global-live-shadow.yml` : manuel/read-only ;
- `v4-global-market-offline-validation.yml` : CI Global ;
- Robot KB : workflows séparés ;
- V5 lives : manuels/expérimentaux ;
- `v5-gcc-catalog-refresh.yml` reste support legacy actuel.

Voir `docs/project-workflow-inventory.md`.

## Branches

Les branches #147/#148 sont conservées comme provenance et aucune suppression n'est implicite. Toute suppression exige audit d'atteignabilité/supersession + autorisation destructive explicite.

Voir `docs/project-branch-inventory.md`.

## Issues

Le dernier audit exhaustif hors PR comptait 3 issues :

- #1 : registre V4 vivant ;
- #28 : historique/completed ;
- #58 : planning Robot KB stale/superseded-by-delivered-stack.

Ne pas fermer/réécrire une issue de housekeeping sans autorisation explicite.

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