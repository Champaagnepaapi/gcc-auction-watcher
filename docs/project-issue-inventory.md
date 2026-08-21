# Robot Pokémon / GCC Auction Watcher — inventaire des issues

> Audit GitHub re-vérifié le **21 août 2026**. Ce fichier couvre les vraies Issues GitHub hors pull requests.

## Résultat exhaustif

GitHub Search retourne exactement **4 issues uniques** :

| Issue | État / rôle | Classification | Instruction |
|---|---|---|---|
| #1 `V4 Run Registry — ChatGPT log access` | OPEN / registre V4 vivant | `ACTIVE_V4_RUN_REGISTRY` | Conserver ouverte. Métadonnées minimales des runs V4, jamais logs complets/secrets. |
| #28 `V4 — independent external market valuation before terminal GCC rejection` | CLOSED / spec historique livrée | `SUPERSEDED_BY_IMPLEMENTATION` | Ne pas rouvrir pour réimplémenter l'architecture external-market. |
| #58 `KB: harvest proven GCC SOLD sales + rotate fixed backup coverage` | OPEN / plan historique livré | `STALE_PLANNING_ISSUE` | Ne pas traiter comme backlog neuf ni fermer automatiquement. |
| #150 `Global Run Registry — ChatGPT log access` | OPEN / registre Global vivant | `ACTIVE_GLOBAL_RUN_REGISTRY` | Conserver ouverte. Source des `run_id` des vrais schedules Global depuis PR #151. |

Contrôle live : **4 issues, 4 uniques**.

---

# Issue #1 — registre V4 vivant

Contrat : métadonnées minimales des runs V4, puis lecture des logs originaux via GitHub. Aucun log complet ni secret stocké dans l'issue.

Classification : `ACTIVE_V4_RUN_REGISTRY`.

**Ne pas mélanger les runs Global dans #1.**

---

# Issue #150 — registre Global vivant et prouvé

PR #151 fait écrire chaque vrai `schedule` de `.github/workflows/v4-global-notify.yml` dans #150 avec uniquement :

- timestamp UTC ;
- `run_id`, attempt, trigger, commit SHA ;
- activation et outcome ;
- inventaire / selected / pending ;
- compteurs TCGdex/PPT/PokeTrace ;
- confirmed candidates / notifications sent ;
- flags `automatic_purchase`, `automatic_bid`, `automatic_checkout`, `automatic_payment`.

Sécurité : aucun log complet, secret/token/cookie/session, détail listing-level ou donnée de paiement. `workflow_dispatch` n'écrit pas dans ce registre.

Classification : `ACTIVE_GLOBAL_RUN_REGISTRY`.

Preuve live : premier commentaire automatique post-#151 = run `32411433425`, trigger schedule, commit `c9539ca...`, activation true, mode `GLOBAL_MARKETPLACE_NOTIFICATION_ACTIVE`, status success, 0 sent, transactions false.

La cadence #153 à toutes les 10 minutes est également visible dans le registre ; exemple récent avant merge #154 : run `32443663511` sur `e79e939c...`, success.

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

Avant de créer/reprendre une issue : vérifier son état live, comparer body et code/PRs actuels, consulter le capability ledger, suivre les supersessions et distinguer registre vivant, spec historique livrée et vraie tâche pending.

Une issue ouverte n'est pas automatiquement du backlog.