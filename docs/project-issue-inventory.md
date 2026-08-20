# Robot Pokémon / GCC Auction Watcher — inventaire des issues

> Audit GitHub re-vérifié le **20 août 2026** après la création du registre Global #150. Ce fichier couvre les vraies Issues GitHub hors pull requests.

## Résultat exhaustif

GitHub Search retourne exactement **4 issues uniques** :

| Issue | État / rôle | Classification | Instruction |
|---|---|---|---|
| #1 `V4 Run Registry — ChatGPT log access` | OPEN / registre V4 vivant | `ACTIVE_V4_RUN_REGISTRY` | Conserver ouverte. Métadonnées minimales des runs V4, jamais logs complets/secrets. |
| #28 `V4 — independent external market valuation before terminal GCC rejection` | CLOSED / spec historique livrée | `SUPERSEDED_BY_IMPLEMENTATION` | Ne pas rouvrir pour réimplémenter l'architecture external-market. |
| #58 `KB: harvest proven GCC SOLD sales + rotate fixed backup coverage` | OPEN / plan historique livré | `STALE_PLANNING_ISSUE` | Ne pas traiter comme backlog neuf ni fermer automatiquement. |
| #150 `Global Run Registry — ChatGPT log access` | OPEN / registre Global vivant | `ACTIVE_GLOBAL_RUN_REGISTRY` | Conserver ouverte. Source des `run_id` des vrais schedules Global depuis PR #151. |

Contrôle live du 20/08/2026 : **4 issues, 4 uniques**.

---

# Issue #1 — registre V4 vivant

Contrat :

- métadonnées minimales de runs V4 ;
- récupération du `run_id`, puis lecture des logs originaux via GitHub ;
- aucun log complet ni secret stocké dans l'issue ;
- registre volontairement ouvert.

Classification : `ACTIVE_V4_RUN_REGISTRY`, pas une dette fonctionnelle.

Ne pas mélanger les runs Global dans #1.

---

# Issue #150 — registre Global vivant

Créée pendant la phase #151 parce que le connecteur ChatGPT disponible sait lire un run connu mais ne peut pas énumérer directement les runs GitHub Actions `schedule` sans `run_id`.

PR #151 fait écrire chaque vrai `schedule` du workflow `.github/workflows/v4-global-notify.yml` dans #150 avec seulement :

- timestamp UTC ;
- `run_id`, attempt, trigger, commit SHA ;
- activation et outcome du runner ;
- inventaire / selected / pending ;
- compteurs TCGdex/PPT/PokeTrace ;
- confirmed candidates / notifications sent ;
- flags `automatic_purchase`, `automatic_bid`, `automatic_checkout`, `automatic_payment`.

Sécurité :

- aucun log complet ;
- aucun secret/token/cookie/session ;
- aucun détail listing-level nécessaire ;
- aucune donnée de paiement ;
- manual `workflow_dispatch` n'écrit pas dans ce registre ;
- issue volontairement ouverte comme registre technique.

Classification : `ACTIVE_GLOBAL_RUN_REGISTRY`.

Le premier commentaire automatique post-#151 doit être utilisé pour récupérer le premier `run_id` schedule production marketplace-first, puis inspecter jobs/logs/artifact originaux.

---

# Issue #28 — external market valuation

État : closed/completed. Ses concepts ont été absorbés par la lignée V4 external-market/canonical multi-market : GCC/externe séparés, `EXTERNAL_RESCUE`, `GCC_EXTERNAL_CONFIRMED`, `EXTERNAL_PENDING`, `MARKET_CONFLICT_BLOCKED`, exact same-card/same-grader/same-grade et budgets/cache bornés.

Classification : `SUPERSEDED_BY_IMPLEMENTATION`.

---

# Issue #58 — Robot KB SOLD + fixed rotation

État : open mais specification historique largement livrée par #59/#60/#62/#68/#72/#75/#76.

Contrat actuel conservé : SOLD final prouvé seulement, `ENDED`/disparition/ask/auction active != vente, fresh SOLD + backfill cursors durables, fixed recent+rotation+targeted, ingestion séparée de V4.

Classification : `STALE_PLANNING_ISSUE / SUPERSEDED_BY_DELIVERED_STACK`.

Ne pas fermer automatiquement sans autorisation utilisateur.

---

# Règle future

Avant de créer/reprendre une issue :

1. vérifier son état live ;
2. comparer body et code/PRs actuels ;
3. consulter le capability ledger ;
4. suivre les supersessions ;
5. distinguer registre vivant, spec historique livrée et vraie tâche pending.

Une issue ouverte n'est pas automatiquement du backlog.