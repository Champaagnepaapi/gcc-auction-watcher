# Robot Pokémon / GCC Auction Watcher — inventaire des issues

> Audit exhaustif GitHub du **17 août 2026**. Ce fichier couvre les vraies Issues GitHub (hors pull requests) et complète le README, le capability ledger, l'inventaire des branches, des PR ouvertes et des workflows.

## Résultat exhaustif

GitHub Search retourne exactement **3 issues** dans ce dépôt :

| Issue | État | Classification | Instruction |
|---|---|---|---|
| #1 `V4 Run Registry — ChatGPT log access` | **OPEN / ACTIVE_REGISTRY** | registre technique vivant | **Conserver ouverte.** Sert volontairement de registre minimal des runs V4 et compte déjà >1000 commentaires. Ne pas la traiter comme une tâche de code non terminée. |
| #28 `V4 — independent external market valuation before terminal GCC rejection` | **CLOSED / COMPLETED / SUPERSEDED_BY_IMPLEMENTATION** | specification historique | Objectif absorbé par la lignée external-market puis canonical multi-market (#29/#33 et durcissements ultérieurs). Ne pas rouvrir pour réimplémenter l'architecture. |
| #58 `KB: harvest proven GCC SOLD sales + rotate fixed backup coverage` | **OPEN / STALE_PLANNING_ISSUE** | plan historique déjà largement livré | Les objectifs ont été implémentés/durcis par Robot KB #59/#60/#62/#68/#72/#75/#76. Ne pas repartir de cette issue comme backlog neuf. Ne pas la fermer automatiquement sans autorisation utilisateur. |

Contrôle : **3 issues, 3 uniques**. Il n'existe pas d'autre issue hors PR au moment du snapshot.

---

# Issue #1 — registre V4 vivant

État vérifié : **open**.

Titre : `V4 Run Registry — ChatGPT log access`.

Contrat explicitement documenté dans l'issue :

- conserver uniquement des métadonnées minimales de runs GitHub Actions V4 ;
- permettre de retrouver les `run_id` et lire ensuite les logs originaux via GitHub ;
- ne pas recopier les logs complets dans le dépôt ;
- ne jamais stocker de secrets ;
- l'issue peut volontairement rester ouverte comme registre technique.

Au moment de l'audit : **1006 commentaires**, dernière mise à jour observée le 17/08/2026.

Classification : `ACTIVE_REGISTRY`, **pas une dette fonctionnelle**.

Réutilisation : pour retrouver les runs V4, consulter cette issue ou l'API Actions ; ne créer aucun second journal parallèle sans besoin démontré.

---

# Issue #28 — external market valuation

État vérifié : **closed**, `state_reason=completed`.

Cette issue spécifiait l'architecture où un rejet local GCC (`empty_history`, `insufficient_comparables`, `insufficient_discount`, prudent max GCC) ne devait plus empêcher une branche externe exacte de valoriser la carte.

Ses concepts ont été matérialisés dans la lignée V4 external-market/canonical multi-market :

```text
#28 specification
 -> PR #29 independent external valuation precursor
 -> PR #33 canonical TCGdex + multi-market production
 -> durcissements providers / safety / queue ultérieurs
```

Concepts à ne pas réinventer :

- GCC et marché externe comme branches d'évidence séparées ;
- `EXTERNAL_RESCUE` ;
- `GCC_EXTERNAL_CONFIRMED` ;
- `EXTERNAL_PENDING` ;
- `MARKET_CONFLICT_BLOCKED` ;
- exact same-card/same-grader/same-grade ;
- provider unavailable/budget deferred != no-match ;
- cache/queue externe bornés.

Classification : `SUPERSEDED_BY_IMPLEMENTATION`. Si un défaut actuel ressemble à #28, auditer d'abord le code production actuel et les PR #29/#33/#43/#47/#77/#116 plutôt que rouvrir l'ancienne architecture.

---

# Issue #58 — Robot KB SOLD + fixed rotation

État vérifié : **open**, mais son corps est une specification du 14/08/2026 basée sur un ancien `main` et une première architecture Robot KB.

Objectifs principaux de #58 :

1. harvester de **GCC SOLD final prouvé** ;
2. ne jamais transformer `COMPLETED`, disparition, ask ou auction ended en vente ;
3. snapshot auction <=5 min reste `LISTING_SNAPSHOT` ;
4. rotation fixed durable ;
5. cursor avance uniquement après ingestion réussie ;
6. collecte GET-only, asynchrone, séparée de V4 ;
7. déduplication/idempotence des ventes.

Ces objectifs ont été réalisés et durcis ensuite :

```text
Issue #58
 -> PR #59/#60 : explicit GCC SOLD contract + deployment
 -> PR #61/#62 : durable fixed rotation (prendre #62)
 -> PR #68 : lossless SOLD watermark + boundary IDs
 -> PR #72 : fresh SOLD lane every 30 min
 -> PR #75 : fixed hybrid 100 recent + 200 rotation + 100 targeted
 -> PR #76 : durable historical SOLD backfill
```

État production/KB actuel :

- `SALE_TRANSACTION` exige `status=SOLD` + `soldAt` timezone-aware + prix final positif ;
- `ENDED`/missing soldAt/auction active ne devient pas une vente ;
- fresh SOLD et historical backfill ont des cursors durables séparés ;
- state n'avance qu'après ingestion Neon réussie ;
- fixed hybrid couvre recent + rotation + targeted ;
- workflow SOLD tourne à `17,47 * * * *` ;
- workflow Robot KB cloud tourne à `32 * * * *` ;
- les deux restent séparés de la décision commerciale V4.

Classification : **`STALE_PLANNING_ISSUE / SUPERSEDED_BY_DELIVERED_STACK`**.

Important : l'issue est encore ouverte. Ne pas la fermer automatiquement ; une fermeture/annotation de housekeeping est une mutation de projet et nécessite instruction explicite utilisateur.

---

# Règle future

Avant de créer une nouvelle issue ou reprendre une issue ancienne :

1. vérifier son état GitHub réel ;
2. comparer son body au code/PRs actuels ;
3. chercher la capability dans `docs/project-capability-ledger.md` ;
4. suivre les supersessions ;
5. distinguer **registre vivant**, **specification historique livrée** et **vraie tâche encore en attente**.

Une issue `open` n'est pas automatiquement une tâche à coder. Une issue `closed` n'est pas du travail perdu : sa specification peut expliquer les invariants de l'architecture actuelle.
