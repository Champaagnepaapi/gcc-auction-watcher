# Robot Pokémon / GCC Auction Watcher — inventaire workflows GitHub Actions

> Audit du **17 août 2026**. Ce fichier distingue les workflows réellement présents dans le tree `main` des anciens enregistrements encore visibles dans l'API GitHub Actions.

## Résultat clé

Deux nombres différents doivent être conservés :

- **14 fichiers workflow existent réellement dans le tree `main` courant** ;
- l'API GitHub Actions retourne **80 enregistrements de workflows** avec `state=active`.

Ces nombres ne sont **pas contradictoires**. GitHub conserve des enregistrements historiques de workflows dont le fichier n'existe plus sur le default branch. Exemple vérifié : `append-readme-pr65.yml` apparaît encore dans l'API Actions mais un fetch du fichier sur `main` retourne `404`.

**Règle : pour savoir ce qui peut réellement être déclenché depuis le code actuel, le tree Git de `main` est l'autorité. L'API Actions sert à retrouver l'historique et le clutter de workflows.**

Tree `.github/workflows` de `main` vérifié :

```text
0ff115a95e8bbf8e4d04534e8efb343eb93cb128
14 blobs
truncated=false
```

---

# 1. Les 14 workflows réellement présents sur `main`

| Workflow | Trigger réel | Statut projet / notes |
|---|---|---|
| `japan-edge-hunter.yml` | `workflow_dispatch` + cron `23 */6 * * *` | **PROD lane Japan Edge**. Notifications activées par défaut sauf variable fail-safe. ASK japonais reste ASK, pas SOLD. |
| `japan-edge-offline-validation.yml` | `workflow_dispatch` + `pull_request` ciblé | CI offline Japan Edge. Pas d'action économique. |
| `psa-api-diagnostic.yml` | `workflow_dispatch` | Diagnostic manuel PSA Public API. |
| `robot-kb-cloud-shadow.yml` | `workflow_dispatch` + cron `32 * * * *` | Collecte Robot KB fixed/auction + TCGdex optionnel. Écrit l'historique KB/Neon, aucune transaction commerciale. |
| `robot-kb-sold-shadow.yml` | `workflow_dispatch` + cron `17,47 * * * *` | Lane Robot KB SOLD + backfill + analytics read-only. Contrat SOLD strict. |
| `v4-auction-discovery-validation.yml` | `workflow_dispatch` + `pull_request` ciblé | CI V4 + comparaison discovery live read-only. |
| `v4-final-auction-check.yml` | `workflow_dispatch` uniquement | Fast Lane production, cadence externe. **Aucun schedule GitHub à ajouter.** |
| `v4-gcc-coverage-audit.yml` | `workflow_dispatch` | Audit GCC manuel/read-only. Providers externes désactivés dans ce diagnostic. |
| `v4-global-live-shadow.yml` | `workflow_dispatch` uniquement | Global Multi-Vault shadow manuel. `NTFY_TOPIC=""`, notify=false, fail-closed si la branche choisie n'a pas les scripts shadow. |
| `v4-global-shadow-dispatch-ci.yml` | `pull_request` ciblé | Vérifie que le dispatcher global reste manuel/read-only. |
| `v4-kb-shadow-ingest.yml` | `workflow_run` après succès `GCC Auction Watcher` | Ingestion passive de la spool V4 vers Robot KB/Neon. Le fix dépendances de PR #54 est déjà présent ici. |
| `v5-gcc-catalog-refresh.yml` | `workflow_dispatch` + cron `17 3 * * *` | **Support V5 legacy encore présent** : maintient `gcc_catalog_index.json`. Le live raw diagnostic restaure encore ce cache. Ne pas supprimer sans audit dédié malgré TCGdex-first actuel. |
| `v5-live-raw-pipeline-diagnostic.yml` | `workflow_dispatch` uniquement | Diagnostic V5 manuel. `RAW_MAX_PAID_GRADINGS_PER_RUN=0`, paid CardGrader=false. |
| `watcher.yml` | `workflow_dispatch` uniquement | **V4 production canonique**, cadence externe Cron-job.org. Aucun schedule GitHub parallèle. |

## Triggers automatiques réellement présents dans le tree courant

GitHub cron :

```text
Japan Edge Hunter        23 */6 * * *
Robot KB cloud shadow    32 * * * *
Robot KB SOLD shadow     17,47 * * * *
V5 GCC Catalog Refresh   17 3 * * *
```

Événement automatique :

```text
V4 KB shadow ingest <- workflow_run successful GCC Auction Watcher
```

Cadence externe, pas GitHub cron :

```text
GCC Auction Watcher
GCC Final Auction Check
```

Tout le reste des 14 fichiers est manual/PR CI selon la table.

---

# 2. Point de vigilance : V5 GCC Catalog Refresh

Le deep audit a confirmé un vestige volontairement encore fonctionnel :

- `v5-gcc-catalog-refresh.yml` tourne quotidiennement à `03:17 UTC` ;
- il maintient le cache cumulatif `gcc_catalog_index.json` ;
- `v5-live-raw-pipeline-diagnostic.yml` restaure explicitement ce même cache.

L'architecture V5 d'identité normale est désormais TCGdex-first et l'ancien catalogue GCC n'est plus l'autorité primaire. **Mais supprimer ce workflow maintenant casserait potentiellement le diagnostic V5 live historique qui consomme encore son cache.**

Classification : `MAIN_SUPPORT / LEGACY_DEPENDENCY`. Une future simplification doit d'abord retirer ou remplacer proprement cette dépendance du live diagnostic, avec tests, puis seulement retirer le refresh.

---

# 3. API Actions : 80 enregistrements historiques

L'API `actions/workflows` retourne exactement **80** enregistrements. Beaucoup portent `Temp`, `One-shot`, `README handoff` ou des diagnostics d'anciennes phases. Ils sont utiles comme index historique mais **66 ne correspondent plus à un fichier dans le tree `main` courant**.

Liste exhaustive 80/80 des chemins enregistrés :

```text
append-readme-pr65.yml
chatgpt-catalog-resolver-ci.yml
chatgpt-gcc-cumulative-index-ci.yml
chatgpt-gcc-search-fix-ci.yml
chatgpt-one-shot-v4-v5-fix.yml
chatgpt-pr-validation.yml
dispatch-v5-live-once.yml
docs-handoff-patcher-temp.yml
docs-tcgdex-run1054-handoff-v2.yml
docs-tcgdex-run1054-handoff.yml
docs-v5-handoff-temp.yml
docs-v5-outage-cache-handoff.yml
japan-edge-global-live-once.yml
japan-edge-hunter.yml
japan-edge-live-once-v2.yml
japan-edge-live-once.yml
japan-edge-offline-validation.yml
japan-edge-one-shot-20260816-0141.yml
japan-edge-ppt-exact-set-one-shot.yml
kb-one-shot-migration-test-update.yml
kb-sold-live-validation.yml
mislisted-cert-live-validation.yml
pr63-readme-eof-fix.yml
pr63-readme-handoff.yml
pr64-readme-update.yml
psa-api-diagnostic.yml
readme-handoff-once.yml
readme-v5-pr93-handoff-one-shot.yml
robot-kb-cloud-shadow.yml
robot-kb-macro-cache-offline.yml
robot-kb-sold-shadow.yml
source-scout-tcgapi-identity.yml
tmp-cert-number-coverage-100.yml
tmp-fix-japan-edge-readme-typo.yml
tmp-japan-edge-doc-append-v2.yml
tmp-japan-edge-doc-append.yml
tmp-japan-edge-notification-layout-readme.yml
tmp-pr66-readme-handoff.yml
tmp-v4-cert-alerts-readme.yml
v4-auction-discovery-validation.yml
v4-cert-focus-live-check.yml
v4-external-budget-live-benchmark.yml
v4-final-auction-check.yml
v4-gcc-coverage-audit.yml
v4-global-live-shadow.yml
v4-global-market-offline-validation.yml
v4-global-shadow-dispatch-ci.yml
v4-kb-shadow-ingest.yml
v4-ocr-focus-benchmark.yml
v4-ocr-live-benchmark-50.yml
v4-ocr-live-benchmark.yml
v4-ppt-shadow-offline-validation.yml
v4-ppt-shadow-one-shot.yml
v5-catalog-benchmark-validation-temp.yml
v5-catalog-gap-hardening-one-shot.yml
v5-catalog-identity-benchmark.yml
v5-ci-repair-temp.yml
v5-contract-update-temp.yml
v5-final-full-validation-temp.yml
v5-full-validation-temp.yml
v5-gcc-catalog-refresh.yml
v5-justtcg-fix-validation-temp.yml
v5-live-raw-pipeline-diagnostic.yml
v5-live-run-reporter-temp.yml
v5-neon-cache-probe.yml
v5-offline-resync-validation.yml
v5-offline-validation-temp.yml
v5-offline-validation.yml
v5-poketrace-identity-ci.yml
v5-poketrace-offline-validation.yml
v5-post-codex-fix.yml
v5-post-macro-retry-one-shot.yml
v5-post-sync-validation-temp.yml
v5-promo-set-alias-one-shot.yml
v5-promo-zero-scope-one-shot.yml
v5-targeted-validation-temp.yml
v5-tcgdex-blockers-readonly.yml
v5-uniqueness-ci-temp.yml
v5-wpromo-semantics-one-shot.yml
watcher.yml
```

Contrôle : **80 noms, 80 uniques**.

## 66 enregistrements historiques : ne pas les confondre avec des fichiers actifs

Le fait que l'API Actions retourne `state=active` pour un ancien workflow ne signifie pas que son YAML existe encore sur `main`. Pour une action future :

1. vérifier d'abord le tree `.github/workflows` courant ;
2. si absent, traiter le workflow comme **historical registry record** ;
3. ne pas recréer son fichier juste parce qu'il apparaît dans l'onglet Actions ;
4. ne pas tenter de « nettoyer » ces records sans comprendre le comportement GitHub et sans autorisation explicite.

---

# 4. Classification des anciens workflows enregistrés

Les 66 records hors tree se répartissent principalement en :

- **one-shot live/benchmark** : Japan Edge, V5 promo/post-macro/cache, PPT, cert/OCR, external budget ;
- **temporary CI** : nombreux `v5-*-temp.yml`, anciens ChatGPT PR validation ;
- **README/docs handoff** : `append-readme-*`, `pr63-*`, `pr64-*`, `tmp-*-readme-*`, `docs-*-handoff-*` ;
- **benchmarks/providers** : Source Scout tcgapi, V5 catalog/JustTCG, OCR/cert ;
- **anciens diagnostics V5** consolidés ensuite par V5 Offline Validation / V5 Live Raw Pipeline Diagnostic ;
- **anciens workflows de migration Robot KB** devenus inutiles comme fichier permanent après la phase.

Ces records sont **de la mémoire historique**, pas 66 workflows production supplémentaires.

---

# 5. Règle future

Avant d'ajouter un workflow :

1. vérifier les 14 fichiers courants ;
2. chercher le besoin dans les 80 records historiques ;
3. chercher la capacité dans le capability ledger/branch inventory ;
4. réutiliser un workflow consolidé quand il existe ;
5. préférer `workflow_dispatch` pour diagnostics/lives ponctuels ;
6. ne jamais ajouter un cron GitHub parallèle à V4 Main Scanner/Fast Lane ;
7. après une phase one-shot, ne pas laisser un nouveau YAML permanent sans justification.

Aucune suppression de workflow ou de record historique n'a été effectuée pendant cet audit.
