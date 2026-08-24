# Robot Pokémon / GCC Auction Watcher — phase courante

État vérifié le **24 août 2026** après merge #175 et preuves production post-fix.

## Autorité

```text
V4 production                  main @ 950694d66b04112fc1182f0b21d6008bb4560204
V4 eBay hang isolation        #175 MERGED / PROD PROUVÉE
Global discovery               marketplace-first
Global scale                   #156 MERGED / batch 50
Global cadence                 20 min
Global schedule registry       issue #150 / PROUVÉ LIVE
Magi native identity           #173 MERGED / PROD
Magi coverage                  #174 OPEN / DRAFT / NON MERGED
Robot KB storage               PostgreSQL local Mac ACTIF
Neon writers                   AUTOMATIQUES OFF / rollback manuel conservé
V5                             PR #8 / draft / non mergée
```

Toujours re-vérifier le HEAD GitHub live ; des commits docs-only peuvent suivre le SHA runtime.

## Incident V4 eBay — clos techniquement

Deux runs V4 (`32664106071`, `32682740195`) ont bloqué environ 6 h sur un deadlock Playwright/eBay. Comme le workflow V4 utilise une concurrency unique avec `cancel-in-progress=false`, les runs suivants de la même lane attendaient derrière, ce qui pouvait créer une fenêtre de non-scan pendant des enchères actives.

#175 isole eBay dans un sous-processus avec hard timeout/kill fail-closed. Production post-merge sur `950694d...` :

```text
32738091183   SUCCESS   578 s
32739149539   SUCCESS   464 s
32740157203   SUCCESS   496 s
32741180104   SUCCESS   598 s
32742259467   SUCCESS   129 s
```

Le mode de panne 6 h n'est plus observé. Continuer la surveillance lors des périodes d'enchères denses, notamment le dimanche.

## Global / Magi

#173 est en production et permet l'identité commerciale japonaise native après preuve TCGdex japonaise exacte, sans imposer une traduction/projection latine.

Preuve prod #173 : run `32634964197`, SUCCESS, Magi 9 exact, safety verte.

#174 est la ligne active pour réduire les rejets Magi restants uniquement avec des preuves déterministes. Dernier head avant synchronisation post-#175 : `b2bb6087cd7d6122b20a9a919839334f09e773a6`.

#174 doit être reprise sur le `main` courant avant nouvelle modification. **Aucun merge de #174 sans autorisation explicite.**

## Robot KB

Migration Neon → PostgreSQL local exécutée et vérifiée :

```text
lignes source/local            1,087,015
nombre de tables               35
marker                         MIGRATION_VERIFIED
PostgreSQL health              OK
schema versions                [1, 2]
```

Collecte locale : fixed/auction `:32`, SOLD fresh/backfill `:17/:47`, backup `03:10`, 7 dumps locaux. `WAITING_FOR_PAYMENT` reste non-SOLD. `V4_USE=false`.

PR #166 a retiré les triggers automatiques Neon. Neon reste rollback/recovery manuel et n'est pas supprimé.

## TCGdex

- `variants_detailed` reste une preuve microvariante déterministe après identité exacte ;
- source pin japonais immuable prioritaire lorsqu'il existe ;
- PR #159 reste séparée, ouverte/non mergée et doit être revalidée contre le `main` courant avant décision ;
- aucune identité incertaine ne devient comparable exact.

## V5

PR #8 reste **OPEN / DRAFT / NON MERGED** sur `agent/v5-poketrace-cardmarket-market-data`.

Ne jamais merger #8 sans autorisation explicite utilisateur.

## Prochaine phase recommandée

1. Reprendre #174 sur `main@950694d...` sans perdre le hotfix #175.
2. Continuer la récupération Magi uniquement si la preuve est déterministe ; ambiguïtés/variantes sensibles restent fail-closed.
3. Surveiller V4 pendant le prochain pic d'enchères, en particulier dimanche.
4. Laisser le backfill PostgreSQL local continuer et surveiller health/logs/backups.
5. Garder Neon comme rollback manuel.

Aucun achat, bid, checkout ou paiement automatique.
