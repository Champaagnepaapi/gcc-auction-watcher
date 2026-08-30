# V4 auction safety-net ledger — 30 août 2026

## Incident production

Run Main Scanner `#2914 / 33307847916` sur `main@1a4b18e98937769bb6924a79aca7dcd36729d25a` :

- discovery fixed : `3165/3165 COMPLETE` ;
- enchères découvertes `<=60 min` : `5/5` évaluées, `0` différée ;
- coverage auction néanmoins `INCOMPLETE` à cause d'un seul `conflicting terminal statuses` pour une URL déjà observée par l'API puis réintroduite par le safety-net legacy private/weekly.

Ce défaut était comptable : aucune des cinq enchères urgentes n'a été ratée.

## Correctif PR #200

Branche : `fix/v4-auction-safety-net-ledger-20260830`.
Runtime validé : `e52d7cfdf71698ad4439a5495a2bde2a4674650d`.
Base : `main@1a4b18e98937769bb6924a79aca7dcd36729d25a`.

Le safety-net private/weekly ne réintroduit plus, en mode API primaire, une URL déjà présente dans `auction_coverage.listing_ids`. Ces URLs ne sont pas des trous de l'API. Le full legacy fallback reste inchangé et aucun statut terminal existant n'est écrasé ou supprimé.

Diagnostic ajouté : `auction_private_already_observed_suppressed`.

Aucun changement d'identité, de prix, d'horizon `<=60 min`, de priorité `<=5/<=12`, de budget provider, de notification ou de transaction.

## Validation

Workflow `V4 Auction Discovery Validation` : run `33308757285` — `SUCCESS`.

- suite V4 complète : `823` tests, `OK`, `2` skipped ;
- régressions dédiées safety-net : PASS ;
- compilation Python : PASS ;
- YAML : PASS ;
- `git diff --check` : PASS ;
- comparaison live read-only : PASS.

Comparaison live à horizon commun `720 min` :

```text
API primary complete            true
API rows seen                   2200
API timers parsed               2200
effective mode                  AUCTION_API_PLUS_LEGACY_SAFETY_NET
private sales checked           7
weekly sales checked            3
supplemental candidates added   1
supplemental failures           0
effective candidates            823
legacy candidates               301
legacy-only                     0
effective-only                  522
```

Conclusion : la discovery effective stabilisée reste un sur-ensemble du legacy indépendant ; aucun lot legacy n'est perdu par le correctif.

## Statut

PR #200 : `OPEN / READY / NON MERGED` jusqu'à autorisation explicite utilisateur.

Aucun achat, bid, checkout ou paiement automatique.
