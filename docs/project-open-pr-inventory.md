# Robot Pokémon / GCC Auction Watcher — inventaire des PR ouvertes

> Source dynamique de reprise. GitHub live reste l'autorité ultime.

Snapshot vérifié : **18 août 2026, PR #129 ouverte**.

## Résultat exhaustif

GitHub contient désormais **126 pull requests au total** et exactement **16 PR ouvertes**.

| PR | Draft | Head / lignée vérifiée | Classification projet | Instruction |
|---|---:|---|---|---|
| #8 | oui | `agent/v5-poketrace-cardmarket-market-data` | `V5_ONLY` | V5 expérimentale canonique. **Ne jamais merger dans main sans autorisation explicite.** |
| #54 | non | `agent/v4-kb-filter-stdlib-hotfix` | `SUPERSEDED / STALE_OPEN` | Fix déjà présent sur `main`; ne pas merger tel quel. |
| #87 | non | `fix/v4-gcc-only-30pct-notify` | `DEFERRED / BEHAVIOR_CHANGE` | Changement produit séparé; décision explicite requise. |
| #92 | oui | `agent/v5-ppt-identity-shadow` | `V5_ONLY / SHADOW` | PPT identity shadow V5 uniquement. |
| #96 | oui | `agent/v5-catalog-gap-hardening` | `V5_ONLY / DEFERRED` | Catalog gaps V5 uniquement. |
| #106 | oui | `agent/v4-ppt-clean-20260816` | `SHADOW / DEFERRED` | PPT V4 shadow. |
| #107 | oui | `agent/japan-edge-ppt-clean-20260816` | `SHADOW / DEFERRED` | PPT Japan display-only. |
| #108 | oui | `feat/v4-global-multivault-edge-foundation` | `SHADOW / DEFERRED` | Fondation Global Multi-Vault. |
| #109 | oui | `feat/v4-global-live-shadow` | `SHADOW / DEFERRED` | Live shadow multi-vault. |
| #110 | oui | `feat/v4-global-rejection-diagnostics` | `SHADOW / DEFERRED` | Diagnostics multi-vault. |
| #111 | oui | `docs/repo-hygiene-readme-20260816` | `SUPERSEDED / STALE_OPEN` | Ancien snapshot docs; ne pas merger tel quel. |
| #113 | oui | `feat/v4-global-retrieval-hardening` | `SHADOW / DEFERRED` | Retrieval hardening global. |
| #114 | oui | `fix/v4-global-magi-sold-filter` | `SHADOW / DEFERRED` | Child stack globale; ne pas merger directement. |
| #115 | oui | `fix/v4-global-comc-groudon-resolution` | `SHADOW / DEFERRED` | Dernier child stack globale auditée. |
| #126 | oui | `fix/v4-poketrace-exact-provider-bridges-20260818` | `SUPERSEDED / STALE_OPEN` | Ancienne lignée pré-#127/#128; **ne pas merger telle quelle**. |
| #129 | oui | `fix/v4-poketrace-ja-search-regression-20260818` | `CURRENT_RECOVERY / V4` | Corrige la régression de recherche JA post-#128; merge uniquement après CI finale + autorisation explicite. |

Aucune PR de cette table n'est autorisée au merge par le seul fait d'être ouverte ou mergeable.

## Lignée PokeTrace production récente

- #124 merged : structured `card_number` + `game` après identité TCGdex exacte.
- #125 merged : observabilité bornée des rejets provider.
- #127 merged : padding collector-number provider conservé.
- #128 merged : bridges `(Japanese)`, `(Secret)`, préfixe exact de set et alias TCGdex exact.
- #129 current : garde le **nom canonique/romanisé pour le retrieval** et le nom TCGdex localisé uniquement comme **alias d'acceptation** du même `card_id + set_id + localId`.

Production `main` au snapshot : `4737604a1685f344ced65ede1ed49b4a1b9b7f6d`.

Premier run post-#128 : `32119349938` — SUCCESS, PokeTrace `5 attempted | 0 exact | 5 no-match`; les cinq probes JA ont renvoyé `provider_candidates=0`, contrairement au run post-#127 qui retrouvait des candidats via le nom canonique/romanisé.

## PR #87 — décision produit séparée

Le `main` courant conserve historiquement :

```text
V4_ILLIQUID_GCC_ONLY_MIN_UPSIDE_RATIO = 1.75
V4_ILLIQUID_GCC_ONLY_MIN_ABSOLUTE_UPSIDE_EUR = 10
```

#87 propose une autre politique. Ne pas l'absorber dans un travail provider/identité.

## Stack Global Multi-Vault

```text
#108 foundation
 -> #109 live shadow
 -> #110 rejection diagnostics
 -> #113 retrieval hardening
 -> #114 Magi SOLD filter
 -> #115 COMC exact-set route
```

## Historique TCGdex recovery

PR #122 et PR #123 sont mergées/fermées; #123 a livré la récupération déterministe au `main` avant la lignée PokeTrace. Le SHA historique `a2878cae20987e3ff16c8aedf6f67d07957f039f` correspond au main post-#123.

## Règle de fraîcheur

Mettre à jour ce fichier lorsqu'une PR est créée, mergée, fermée, change de statut fonctionnel ou de chaîne de supersession. Pour toute décision de merge, re-vérifier GitHub live.