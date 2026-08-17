# Robot Pokémon / GCC Auction Watcher — inventaire des PR ouvertes

> **Source dynamique de reprise pour les PR encore ouvertes.**
>
> Ce fichier complète `README.md`, `docs/project-capability-ledger.md` et `docs/project-branch-inventory.md`. Les statuts GitHub réels restent l'autorité ultime ; ce snapshot sert à empêcher qu'une vieille PR ouverte soit oubliée ou prise à tort pour de la production.

Snapshot vérifié : **17 août 2026**.

## Résultat exhaustif

GitHub Search retourne **120 pull requests au total** dans le dépôt et exactement **16 PR ouvertes** au moment de cet audit. Les 16 ouvertes ont été vérifiées individuellement ou dans leur stack fonctionnelle. Les anciennes PR ont également été parcourues pendant l'audit de capacités afin de reconstruire les chaînes de supersession documentées dans le capability ledger.

| PR | Draft | Head vérifié | Classification projet | Instruction |
|---|---:|---|---|---|
| #8 | oui | `bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f` | `V5_ONLY` | V5 expérimentale canonique. **Ne jamais merger dans main sans autorisation explicite.** |
| #54 | non | `55aa8af90be720b69e6d61cf0f37190a588e3275` | `SUPERSEDED / STALE_OPEN` | Son unique fix `pip install -r requirements.txt` avant le filtre KB est déjà présent sur `main`. Ne pas merger tel quel. |
| #87 | non | `28659a2254a115caf59c01f039a75d7675ccaf75` | `DEFERRED / BEHAVIOR_CHANGE` | Vrai changement encore non production : ntfy GCC-only illiquide dès 30 %, >=2 GCC SOLD, floor absolu 0 €. Nécessite décision explicite avant reprise/validation/merge. |
| #92 | oui | `772353311abac836afbc618047a5e2b146806e36` | `V5_ONLY / SHADOW` | PPT identity shadow V5. Retrieval/helper seulement, pas autorité automatique. |
| #96 | oui | `360ae33a67987e0a981b348e636bd7e2f964667e` | `V5_ONLY / DEFERRED` | Rejet Pocket digital + curated physical catalog gaps. Non mergée dans V5. |
| #106 | oui | `b2372ceed1591075466df9334255d353534d8b1d` | `SHADOW / DEFERRED` | Clean PPT V4 shadow, successeur de #90. |
| #107 | oui | `7d70844b5511c13f809c7686e2a64c3f705802c4` | `SHADOW / DEFERRED` | PPT Japan display-only, successeur de #95/#105. |
| #108 | oui | `e2a6fafeaa4a607010f0bd7378bc70caa708f306` | `SHADOW / DEFERRED` | Fondation Global Multi-Vault. Ne pas intégrer seule : suivre la stack complète jusqu'à #115. |
| #109 | oui | `f3f94c4436b60e307f6ea8e5d97b92d3347d5db2` | `SHADOW / DEFERRED` | Live shadow multi-vault. |
| #110 | oui | `fa98713591f002eb0238e4535b718a037f90f86f` | `SHADOW / DEFERRED` | Diagnostics de rejet multi-vault. |
| #111 | oui | `170c5f670dfa60b14d5d9741257259632bc3dadc` | `SUPERSEDED / STALE_OPEN` | Ancienne refonte README/repo hygiene basée sur un main ancien. PR #123 contient un handoff/ledger/inventaire plus récent et plus complet. Ne pas merger #111 tel quel. |
| #113 | oui | `a771b783fbcd98c4fdb6ba1008df35fa83263b54` | `SHADOW / DEFERRED` | Retrieval hardening magi/Fanatics/COMC. |
| #114 | oui | `c40aa846ce5fdc4213afa0895e4440a04995b85a` | `SHADOW / DEFERRED` | Rejet des pages Magi explicitement SOLD dans la lane ASK. |
| #115 | oui | `e9906b97ee54251fb4ff85417c5a8556da9068a1` | `SHADOW / DEFERRED` | Route COMC exact-set facet. Dernier child de la stack globale auditée. |
| #122 | non | `e8f00ef1cd36059ba08e8c7a27a18eb8183cdd18` | `DEFERRED / SUPERSEDED_CANDIDATE` | Fallback TCGdex coordonnée unique validé. PR #123 l'étend avec la capacité V5 #31 et la mémoire durable. Garder ouverte jusqu'à décision explicite. |
| #123 | oui | **head mobile — re-vérifier GitHub avant toute action** | `DEFERRED / CURRENT_RECOVERY` | Candidate actuelle de récupération globale + backport TCGdex. Son SHA final est volontairement consigné dans la PR/CI plutôt que dans ce fichier auto-modifiant. |

Aucune PR de cette table n'est autorisée au merge par le seul fait d'être ouverte/mergeable.

---

# Cas importants retrouvés pendant le deep audit

## PR #54 — ouverte mais déjà absorbée par `main`

PR #54 ajoutait uniquement l'installation des dépendances V4 dans `V4 KB shadow ingest` avant le filtre Python.

Le workflow `main` courant contient déjà :

```yaml
- name: Set up Python
  uses: actions/setup-python@v5
  with:
    python-version: "3.12"
    cache: pip
    cache-dependency-path: requirements.txt

- name: Install V4 helper dependencies
  run: python -m pip install -r requirements.txt
```

Conclusion : **#54 est stale-open/superseded par l'histoire ultérieure de main**. Ne pas merger. Ne pas fermer automatiquement sans instruction utilisateur.

## PR #87 — réellement non production

PR #87 n'est ni fermée ni draft : elle est **ouverte, non-draft, non mergée**.

Elle propose :

- GCC-only `ILLIQUID_PRICE_DISCOVERY` fixed notifiable dès **30 % de décote** ;
- au moins **2 GCC SOLD exacts** ;
- calcul direct de la décote ;
- floor absolu par défaut **0 €** au lieu de 10 € ;
- external graded SOLD inchangé ;
- auctions silencieuses avant `<=5 min` ;
- aucun changement de FV, `max_recommended`, identity, discovery ou transaction.

Le `main` courant reste sur :

```text
V4_ILLIQUID_GCC_ONLY_MIN_UPSIDE_RATIO = 1.75
V4_ILLIQUID_GCC_ONLY_MIN_ABSOLUTE_UPSIDE_EUR = 10
```

Donc **#87 représente encore une vraie décision produit/économique en attente**. Ne pas la présenter comme production et ne pas l'absorber implicitement dans #123.

## PR #111 — docs historiques superseded

#111 voulait déjà simplifier le README et documenter la forte surface de branches. Son intuition était correcte, mais son snapshot est ancien et incomplet par rapport au deep audit actuel :

- basé sur un ancien `main` ;
- ne connaît pas la chaîne TCGdex #117-#123 ;
- ne contient pas l'inventaire exhaustif 145/145 ;
- ne contient pas l'audit complet des 16 PR ouvertes ;
- ne centralise pas les capacités historiques V4/V5/Robot KB/Source Scout/Global comme #123.

Conclusion : **#111 est un actif historique docs, mais sa fonction est superseded par #123**. Ne pas merger tel quel et ne pas fermer automatiquement.

---

# Stack Global Multi-Vault — PR ouvertes liées

Ces PR ne sont pas six fonctionnalités indépendantes à merger séparément. Elles forment une seule lignée :

```text
#108 foundation
 -> #109 live shadow
 -> #110 rejection diagnostics
 -> #113 retrieval hardening
 -> #114 Magi SOLD filter
 -> #115 COMC exact-set route
```

Réutilisation future : repartir de la **dernière stack compatible**, puis rebase/port propre sur le `main` courant. Ne pas merger un child directement sur `main`.

---

# Règle de fraîcheur

Ce fichier doit être mis à jour lorsque :

- une PR est créée, mergée, fermée ou convertie draft/non-draft ;
- son head change de manière fonctionnelle ;
- une PR ouverte devient `SUPERSEDED` parce que sa capacité est déjà absorbée ailleurs ;
- une stack de PR change de successeur autoritaire.

Pour toute décision de merge, **re-vérifier GitHub au moment de l'action** : ce snapshot ne remplace jamais l'état live du dépôt.
