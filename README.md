# GCC Auction Watcher

> **Source de reprise technique canonique — lire ce fichier en premier dans toute nouvelle conversation.**
>
> Le code/Git/GitHub live reste l'autorité. Les SHA ci-dessous sont des ancres de reprise : toujours re-vérifier `main`, les PR et les workflows live avant une action importante.

## État canonique — 7 septembre 2026

Repo : `Champaagnepaapi/gcc-auction-watcher`

```text
V4 production branch                 : main
V4 production logic HEAD             : db4954f5b223817fe14ccfeb9dcac80c960d5dd9
#255 external fair-value authority    : MERGED / PROD_V4
#259 recall/PriceCharting/Global/Japan: MERGED / PROD_V4
#260 TCGdex constrained recovery      : MERGED / PROD_V4
#261 cross-grader calibration         : OPEN / DRAFT / base pré-#260 / NON MERGED
Robot KB durable                      : PostgreSQL local Mac / V4_USE=false
Neon                                  : writers automatiques OFF / rollback manuel
P3/Cardova durable                    : #210 OPEN / DRAFT / autorisation explicite requise
V5 expérimentale                      : PR #8 / OPEN / DRAFT / NON MERGED
TCGdex source pin                     : af33c9ac882e2acfadffaf19e8083aa976d12983
```

Le SHA `db4954f5...` est le **SHA logique production post-#260**. Un futur commit docs-only peut faire avancer `main` sans modifier ce runtime ; toujours distinguer HEAD documentaire et SHA logique runtime.

---

# Principes non négociables

- **V4 sur `main` = production canonique.**
- **PR #8 / V5 ne doit jamais être mergée dans `main` sans autorisation explicite utilisateur.**
- Pokémon **cartes individuelles uniquement** ; sealed/lots hors scope.
- Aucun achat, bid, checkout, paiement ou grading payant automatique.
- Aucun secret, token, cookie, session ou mot de passe dans le repo ou les logs.
- Identité incertaine, contradictoire ou microvariante non prouvée = fail-closed / revue manuelle.
- Ne jamais mélanger langue, set, numéro, grader, grade, édition, finish ou microvariante incompatible.
- ASK, enchère live et disparition d'annonce ne deviennent jamais des ventes.
- Une panne provider, un 403/429 ou un timeout ne devient jamais un clean no-match.
- Robot KB/Neon restent séparés de la décision commerciale V4 tant que `V4_USE=false`.

## Hiérarchie de preuve prix

1. SOLD exacts et récents ;
2. SOLD exacts plus anciens avec ajustement temporel prouvé ;
3. fixed ASK compatibles, explicitement marqués ASK ;
4. snapshot d'enchère observé à `<=5 min` de la fin si aucun SOLD exploitable n'existe ;
5. enchère en cours = signal faible seulement.

Aucun ASK, guide agrégé ou snapshot live n'est présenté comme un item-level SOLD.

---

# V4 — production canonique

## Main Scanner

```text
Cron-job.org ~toutes les 10 min
  -> workflow_dispatch
  -> .github/workflows/watcher.yml
  -> run_watcher_multimarket_resilient.py
  -> run_watcher_multimarket.py
```

Le Main Scanner est cadencé extérieurement. **Ne jamais ajouter un cron GitHub parallèle.** Son registre actif est l'issue #235.

## Politique économique production post-#259

```text
MAX_PRICE_EUR                    250
MIN_DISCOUNT_PCT                 20
V4_RECALL_MIN_DISCOUNT_PCT       20
PSA numeric scope                1-10
synthetic PSA 9.5                interdit
```

Le seuil réel reste adaptatif : une preuve plus faible/ancienne/sparse peut exiger davantage que 20 %. Le plancher 20 % n'autorise jamais à relâcher l'identité.

### Autorité de fair value

#255 reste l'invariant : **l'historique GCC est observationnel**, il ne peut ni créer, ancrer, confirmer, plafonner ni conflict-block une fair value.

#259 sépare les rôles :

```text
opportunity/listing sources
  GCC / Fanatics / COMC / Magi / Cardova / Japan adapters
        ↓
identité commerciale stricte + TCGdex
        ↓
valuation providers externes
  SOLD-derived exacts lorsqu'ils existent
  PokeTrace / PSA APR
  PriceCharting GUIDE
        ↓
décision économique
```

- direct eBay SOLD scraping n'a plus d'autorité de fair value dans cette phase ;
- PriceCharting est consulté comme **GUIDE**, jamais item-level SOLD ;
- `Grade 8/9/PSA 10` PriceCharting n'est utilisé que lorsque le grade cible exact est déjà prouvé ; PSA 8.5 reste distinct ;
- une panne PriceCharting ne détruit pas une preuve SOLD plus forte déjà établie ;
- PokeTrace reste agrégé : son centre peut être utile si identité/langue/grader/grade exacts sont prouvés, mais aucun item-level SOLD ni distribution artificielle n'est fabriqué ;
- ASK eBay actif exact = revue secondaire seulement, `ASK` explicite, haircut production 10 %, max 4 lookups/run, seuil de revue 20 % ; jamais SOLD.

## TCGdex — identité exacte et #260

TCGdex reste l'autorité d'identité. `variants_detailed` peut prouver les axes matériels après résolution exacte. Axes inconnus, multiples, malformés ou contradictoires => blocage.

#260 ajoute un **recovery de nom très contraint**, sans transformer le fuzzy en preuve autonome :

1. set + numéro imprimé + dénominateur doivent déjà être exacts ;
2. les contraintes de langue/coordonnée/microvariante restent actives ;
3. il doit rester **exactement un** candidat compatible après comparaison de nom ;
4. une différence matérielle de nom reste bloquante ;
5. deux candidats compatibles ou plus => `AMBIGUOUS` ;
6. grader/grade et économie ne sont jamais déduits par ce recovery.

Ce recovery ne remplace pas les couches exact-coordinate/source-pinned existantes et ne crée aucun alias carte-par-carte.

### Validation #260

```text
validated head                   d809f4aacce0cbfb362546a65de351be2451dcf6
CI run                           34053317112
CI job                           101541221319
V4 suite                         958 PASS / 2 skipped
compile                          PASS
YAML                             PASS
git diff --check                 PASS
read-only auction compare        PASS
merge/runtime SHA                db4954f5b223817fe14ccfeb9dcac80c960d5dd9
first natural Main post-merge    run 34091885754 / job 101646924190 / SUCCESS
```

Le premier Main Scanner naturel post-merge a checkout exactement `db4954f5...`, avec TCGdex `errors=0` et plusieurs ambiguïtés conservées fail-closed. Le chemin spécifique de recovery fuzzy unique n'a pas été observé naturellement dans cet échantillon : **déploiement + smoke production prouvés, branche fonctionnelle spécifique prouvée par CI mais pas encore live-observée.**

## Auction discovery

Chemin normal : `AUCTION + ON_SALE + ENDING_SOON` avec `endTime` individuel.

- ordre GCC valide : fast path ;
- dérive d'ordre prouvée : récupération exhaustive bornée puis horizon appliqué localement ;
- erreurs requête/pagination/endTime/repeated-page/no-progress : fail-closed vers le fallback legacy existant ;
- `api_total` sert au sizing seulement, jamais à prouver la complétude ;
- statut `COMPLETE` uniquement après preuve d'épuisement réel ou horizon correctement franchi dans un ordre vérifié.

Recovery : page size 100, budget adaptatif `ceil(api_total/page_size)+2`, hard ceiling 250, economic cap 360, priorité `<=5 min -> <=12 min -> <=60 min`.

Protections production à préserver : #211/#212, #220/#243, #229/#231, #245.

## Queue fixed / external pending — interprétation correcte du « 21/120 »

`processing budget: 120` est un **plafond global d'évaluations**, pas une cible à remplir.

`V4_EXTERNAL_PENDING_MAX_PER_RUN=16` est un second plafond indépendant pour les anciens `pending retry`. Donc un run sain peut traiter 17, 20, 27, etc. sans anomalie.

Preuves auditées :

```text
run 34085196093 (#4027)   processed 17 = stale 1 + pending retry 16
run 34085768066 (#4028)   processed 27 = stale 11 + pending retry 16
                          External queue selected 21
```

Le « 21/120 » provenait d'un mélange de métriques : `selected 21` = identités retenues pour l'arbitrage provider, **pas** `processed this run: 21`.

Ne pas augmenter les caps uniquement pour « atteindre 120 ». Le backlog externe est réel mais doit être réduit par meilleure efficacité/couverture provider, pas en supprimant les bornes de sécurité.

## Fast Lane

```text
Cron-job.org ~toutes les 3 min
  -> workflow_dispatch
  -> .github/workflows/v4-final-auction-check.yml
  -> recheck ciblé des auctions déjà armées à <=5 min
```

Aucun bid automatique.

---

# Global Multi-Vault / Japan

#259 a intégré la séparation économique des sources et les capacités pertinentes des travaux #257/#258/#256. Les anciennes PR encore ouvertes correspondantes ne doivent **pas** être mergées directement : elles sont à auditer comme provenance/superseded.

Architecture : un orchestrateur, adapters indépendants, identité exacte commune, valuation externe commune. Une marketplace découvre une offre ; son propre prix ne devient jamais sa fair value.

Mercari/SNKRDUNK restent des sources ASK/opportunités read-only dans leur lane ; aucune disponibilité ambiguë ou page explicitement vendue ne devient une offre active, et aucune ASK ne devient SOLD.

---

# Robot KB — PostgreSQL local Mac

Robot KB reste séparé de V4 : `V4_USE=false`.

Contrat durable : observations append-only datées, payload brut + provenance, priorité aux SOLD finaux prouvés, fixed baseline puis changements utiles, auctions SOLD final prioritaire, snapshot `<=5 min` seulement fallback identifié. ASK/live/disparition/`WAITING_FOR_PAYMENT` != SOLD.

Neon : writers automatiques OFF ; rollback/recovery manuel seulement.

## P3 / Cardova durable

- #207 est mergée uniquement dans `agent/p3-postgres-durable-shadow` ;
- #210 reste OPEN/DRAFT/NON-MERGED et prépare seulement un commit durable Cardova gardé par autorisation explicite + backup + locks ;
- aucun write durable Cardova sans autorisation explicite opérateur.

---

# V5 — EXPÉRIMENTALE

```text
PR #8        OPEN / DRAFT / NON MERGED
branch       agent/v5-poketrace-cardmarket-market-data
```

**Ne jamais merger PR #8 dans `main` sans autorisation explicite.**

---

# Gouvernance avant changement important

1. lire entièrement ce README ;
2. lire `.agents/rules/gcc-project-governance.md` ;
3. lire `AGENTS.md` s'il existe ; son absence n'est pas une erreur ;
4. lire capability ledger + inventaires pertinents ;
5. vérifier Git local seulement si le worktree est réellement accessible ;
6. vérifier `main`, SHA, PRs, branches et workflows live ;
7. faire le REUSE AUDIT avant de réimplémenter ;
8. branche/PR dédiée pour changement non trivial ;
9. SHA précis + tests ciblés + suite pertinente ;
10. compile/YAML/`git diff --check` ;
11. live read-only lorsque pertinent ;
12. aucune transaction/secret ;
13. merge seulement avec l'autorisation requise ;
14. mettre à jour README/handoff après une phase importante.

Documents de reprise :
- `docs/project-current-phase.md`
- `docs/project-capability-ledger.md`
- `docs/project-open-pr-inventory.md`
- `docs/project-branch-inventory.md`
- `docs/project-workflow-inventory.md`
- `docs/project-issue-inventory.md`
- `docs/project-repository-snapshot.md`
- `docs/v4-external-fair-value-authority-20260906.md`
- `docs/v4-source-role-pricecharting-20260906.md`

---

# Prochaine direction canonique

- Le principal résiduel production est la **couverture marché externe incomplète**, pas la découverte GCC.
- Ne pas augmenter mécaniquement les caps pour vider le backlog.
- PR #261 est OPEN/DRAFT mais part d'une base pré-#260 : avant toute action, rebase/port propre + REUSE AUDIT + validation complète.
- PR #258/#256 encore ouvertes doivent être traitées comme provenance/superseded par #259 avant toute décision.
- PR #8 reste protégée.

Aucun achat, bid, checkout ou paiement automatique.
