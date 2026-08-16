# V4 Global Live Shadow — validation du 16 août 2026

Cette note documente la phase live shadow empilée sur la PR #108. Elle ne remplace pas le README canonique de `main` et devra être reprise dans `README.md` au moment de l’intégration de la pile.

## Consolidation multi-agent

- PR #106 reste l’implémentation canonique du provider réseau PokemonPriceTracker V4 shadow. PR #109 ne la recopie pas.
- PR #107 reste la lane Japan Edge d’affichage séparé GCC/PPT après décision. PR #109 ne modifie pas sa logique de notification.
- PR #108 fournit la common valuation layer et les adapters de marché ; PR #109 est un child PR de #108.
- PR #8 V5 reste expérimentale, draft, non mergée et hors scope.

## Branche / PR

- PR : #109 `V4 global: wire public markets into read-only live shadow`
- branche : `feat/v4-global-live-shadow`
- base : PR #108 / `e2a6fafeaa4a607010f0bd7378bc70caa708f306`
- head fonctionnel live validé : `aadc43e51f20e12d1eb36588aaa9a47a24c23a2a`
- head final CI après retour du workflow en manuel-only : `a5ee6a92f7d3437b3609eb79a8cd37273c9d7e16`

## Live read-only

Run : `31954247131`
Job : `95182311878`
Conclusion : **SUCCESS**

Le run a utilisé 5 identités Japanese PSA10 disposant d’une fair value issue de SOLD GCC exacts récents. Aucun ntfy, aucune écriture Neon, aucun achat/bid/checkout/paiement et aucune mutation de fichier suivi.

Statut des sources :

| Marché | Recherches | Candidats inspectés | Exact retenu | Statut |
|---|---:|---:|---:|---|
| GCC | 16 | 1600 | 6 | OK, GET public |
| Cardova | 0 | 0 | 0 | `AUTH_SESSION_INPUT_REQUIRED` |
| magi | 5 | 35 | 0 | OK, browser read-only |
| Fanatics | 5 | 24 | 0 | OK, Buy Now read-only |
| COMC | 5 | 2 | 0 | OK, read-only |

Important : **0 exact sur magi/Fanatics/COMC dans ce petit panel n’est pas une preuve d’absence d’inventaire sur ces marchés.** Le matching est volontairement fail-closed.

Cardova n’est pas appelé depuis GitHub Actions car son endpoint observé dépend d’une session navigateur authentifiée. Le robot refuse d’importer cookies/tokens/headers. Un snapshot JSON assaini récupéré dans le même navigateur peut être fourni au CLI sans transmettre de secret.

## Exemple du tableau live

Fair values du panel, toutes issues de `RECENT_EXACT_SOLD_MEDIAN` GCC :

- Pikachu `20/M-P` JP PSA10 : fair €95 ; GCC auction live €100 = signal faible ; GCC fixed ASK €119.
- Mewtwo `183/165` JP PSA10 : fair €155 ; aucune offre exacte retenue dans ce run.
- Groudon `69/62` JP PSA10 : fair €150 ; GCC fixed ASK €300.
- Persian `75/64` JP PSA10 : fair €95 ; GCC fixed ASK €115 et €149.
- Dragonite `246/193` JP PSA10 : fair €430 ; GCC fixed ASK €460.

Les enchères actives ne peuvent pas gagner le classement. Les asks restent des `FIXED_ASK`, jamais des SOLD. Lorsqu’un coût all-in n’est pas prouvé, le rapport l’indique et peut seulement afficher un classement `RAW_ASK_ONLY`.

## Validation offline finale

Run : `31954554108`
Job : `95183060968`
Conclusion : **SUCCESS**

- 33/33 tests global-market PASS ;
- 51/51 régressions V4 multimarket PASS ;
- compilation PASS ;
- parsing des deux workflows YAML PASS ;
- `git diff --check` PASS.

## État de déploiement

- PR #109 reste draft/shadow.
- Le workflow live est revenu en `workflow_dispatch` manuel uniquement après le run contrôlé.
- Aucun wiring dans `run_watcher_multimarket.py`.
- Aucune notification production ajoutée.
- Aucun merge automatique.
