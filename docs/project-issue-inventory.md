# Robot Pokémon / GCC Auction Watcher — inventaire des issues

> Audit GitHub re-vérifié le **3 septembre 2026**. Ce fichier couvre les vraies Issues GitHub hors pull requests.

## Résultat exhaustif

GitHub Search retourne exactement **5 issues uniques** :

| Issue | État / rôle | Classification | Instruction |
|---|---|---|---|
| #1 `V4 Run Registry — ChatGPT log access` | OPEN / archive V4 historique saturée | `V4_RUN_REGISTRY_ARCHIVE` | Conserver ouverte. >2500 commentaires ; ne plus y écrire les nouveaux runs. Aucun log complet/secrets. |
| #28 `V4 — independent external market valuation before terminal GCC rejection` | CLOSED / spec historique livrée | `SUPERSEDED_BY_IMPLEMENTATION` | Ne pas rouvrir pour réimplémenter l'architecture external-market. |
| #58 `KB: harvest proven GCC SOLD sales + rotate fixed backup coverage` | OPEN / plan historique livré | `STALE_PLANNING_ISSUE` | Ne pas traiter comme backlog neuf ni fermer automatiquement. |
| #150 `Global Run Registry — ChatGPT log access` | OPEN / registre Global vivant | `ACTIVE_GLOBAL_RUN_REGISTRY` | Conserver ouverte. Source des `run_id` des vrais schedules Global depuis PR #151. |
| #235 `V4 Main Scanner Run Registry — September 2026 rollover` | OPEN / registre Main Scanner vivant | `ACTIVE_V4_RUN_REGISTRY` | Successeur de #1. Conserver ouverte ; métadonnées minimales des runs naturels V4 uniquement. |

Contrôle live : **5 issues, 5 uniques**.

---

# Issue #235 — registre V4 actif

#237 a déplacé l'écriture du Main Scanner vers #235 après saturation de #1. Le contrat reste : métadonnées minimales seulement, puis lecture des logs originaux via GitHub ; aucun log complet ni secret recopié.

Classification : `ACTIVE_V4_RUN_REGISTRY`.

Preuve naturelle : run `33741053547` sur `9fac4bd5...` = workflow SUCCESS, `scan_exit_code=0`, étape `Register V4 run in issue #235` SUCCESS, discovery auctions `COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS`, `24/24` timers, fallback false.

**Ne pas mélanger les runs Global dans #1 ni #235.** Global reste dans #150.

---

# Issue #1 — archive V4 historique

Issue #1 a atteint la limite GitHub de plus de 2500 commentaires. Elle reste ouverte comme archive/provenance, mais les nouveaux Main Scanner runs ne doivent plus tenter d'y écrire.

Classification : `V4_RUN_REGISTRY_ARCHIVE`.

Ne pas supprimer, réécrire ou compacter automatiquement l'historique.

---

# Issue #150 — registre Global vivant et prouvé

PR #151 fait écrire chaque vrai `schedule` de `.github/workflows/v4-global-notify.yml` dans #150 avec uniquement : timestamp UTC, `run_id`, attempt, trigger, commit SHA, activation/outcome et métriques agrégées sûres.

Sécurité : aucun log complet, secret/token/cookie/session, détail listing-level ou donnée de paiement. `workflow_dispatch` n'écrit pas dans ce registre.

Classification : `ACTIVE_GLOBAL_RUN_REGISTRY`.

---

# Issue #28 — external market valuation

État : closed/completed. Ses concepts ont été absorbés par la lignée V4 external-market/canonical multi-market : GCC/externe séparés, `EXTERNAL_RESCUE`, `GCC_EXTERNAL_CONFIRMED`, `EXTERNAL_PENDING`, `MARKET_CONFLICT_BLOCKED`, exact same-card/same-grader/same-grade et budgets/cache bornés.

Classification : `SUPERSEDED_BY_IMPLEMENTATION`.

---

# Issue #58 — Robot KB SOLD + fixed rotation

État : open mais specification historique largement livrée par #59/#60/#62/#68/#72/#75/#76.

Contrat actuel : SOLD final prouvé seulement, `ENDED`/disparition/ask/auction active != vente, fresh SOLD + backfill cursors durables, fixed recent+rotation+targeted, ingestion séparée de V4.

Classification : `STALE_PLANNING_ISSUE / SUPERSEDED_BY_DELIVERED_STACK`.

Ne pas fermer automatiquement sans autorisation utilisateur.

---

# Règle future

Avant de créer/reprendre une issue : vérifier son état live, comparer body et code/PRs actuels, consulter le capability ledger, suivre les supersessions et distinguer registre vivant, archive de registre, spec historique livrée et vraie tâche pending.

Une issue ouverte n'est pas automatiquement du backlog.
