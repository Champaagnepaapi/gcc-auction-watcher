# Robot Pokémon / GCC Auction Watcher — phase courante

État re-vérifié le **6 septembre 2026** après les merges production #253, #254 et #255. Le code/Git/GitHub live reste l'autorité ; re-vérifier `main` avant toute action importante.

## Autorité

```text
V4 production branch                 main
V4 production HEAD                   9d3bb1b84d22c1534c24d7c58c5897ecce4b817f / #255 MERGED
#255 validated head                  e886c649eea8633d39585aabca8fff0b58be4324
#255 CI                              34036063564 / 34036063610 / 34036063594 SUCCESS
#254 production merge                00e5502fb15c9a89d67a55b70cd566099911bcdb
#254 validated head                  fbb7041f9fc44c338b102ec7325a6d6316f1e529
#254 validation                      34031695933 attempt 2 SUCCESS / 920 PASS / 2 skipped
#253 production merge                23e8e9904072d986e24d2a8fbccaa87568851f69
Fast Lane exact post-#255            34037049703 SUCCESS
Premier Main Scanner post-#255       34037829669 / exact 9d3bb1... / lancé naturellement
V4 run registry                      issue #235 ACTIVE
V5                                   PR #8 OPEN / DRAFT / NON MERGED
Robot KB durable                     PostgreSQL local Mac / V4_USE=false
Neon                                 writers automatiques OFF / recovery manuel
```

## Ce qui vient de changer

### #254 — eBay salvage borné

Deux Main Scanner naturels post-#253 ont montré le chemin pathologique suivant : body timeout -> `body_text_content` timeout -> `items_bulk_text` -> absence de fin de stage -> hard deadline 30 s.

#254 remplace ce salvage pathologique par un probe same-DOM strictement borné : maximum 4 `li.s-item`, `inner_text(timeout=600)` par ligne, exigence EUR/€, re-raise fail-closed si la preuve structurée est insuffisante. Aucun nouveau réseau, retry, budget ou changement SOLD/identité/économie.

### #255 — autorité économique externe uniquement

L'historique GCC n'est plus une fair-value authority. GCC reste l'autorité du listing courant et de son identité/timing, mais ne peut plus créer, confirmer, ancrer ou plafonner la fair value.

```text
external STRONG                   -> chemin économique existant possible
external PENDING / WEAK           -> fail-closed
provider ERROR / UNAVAILABLE      -> fail-closed
fallback GCC_ONLY                 -> interdit
rejet GCC terminal de sécurité    -> reste terminal
```

Aucune définition SOLD, identité, langue, grader, grade, microvariante, limite provider ou transaction automatique n'est relâchée.

## Preuve production en cours

Le premier Main Scanner observé sur l'exact SHA post-#255 est :

```text
run      34037829669
workflow GCC Auction Watcher
head     9d3bb1b84d22c1534c24d7c58c5897ecce4b817f
event    workflow_dispatch externe / cadence naturelle
```

Tant qu'il n'est pas terminé et que ses logs ne sont pas audités, ne pas revendiquer de preuve live complète #254/#255 sur le Main Scanner. Ne pas lancer un scanner manuel en parallèle.

À auditer dès completion :
- eBay `body_text_content` / structured salvage / hard-timeout ;
- attempted / sufficient / insufficient / unavailable / errors ;
- PSA APR 403 et breaker ;
- TCGdex / PokeTrace ;
- fixed/external backlog et auction scope ;
- absence de `GCC_ONLY` economics ;
- external weak/pending/error bien fail-closed ;
- strong externe encore capable de rescue si rencontré.

## Nouvelle phase : couverture SOLD externe

Le scanner GCC/discovery est désormais suffisamment durci pour que le principal rendement marginal vienne de la **qualité et couverture des preuves marché externes**.

Priorité canonique :

1. SOLD exacts récents item-level ;
2. SOLD exacts anciens ajustés temporellement si défendable ;
3. ASK fixes compatibles ;
4. auction snapshot ≤5 min seulement si aucun SOLD ;
5. active auction = signal faible.

### Reuse audit du 6 septembre

- **eBay V4** : source SOLD immédiate la plus utile ; conserver #137/#175/#189/#238/#239/#241/#242/#250/#251/#252/#253/#254. Améliorer la couverture seulement après preuve du bottleneck live ; ne pas augmenter les caps pour masquer des erreurs.
- **eBay RapidAPI Robot KB** : shadow existant. Les rows restent `genuine_sale_evidence=false` tant que finalité/prix exacts ne sont pas corroborés indépendamment.
- **Fanatics #197** : provider-level `PAID + isComplete=true` prouvé sur des cartes individuelles PSA. La devise n'était pas prouvée dans le contrat validé ; conserver en pending evidence jusqu'à fermeture explicite devise + identité + microvariante.
- **COMC #198** : anonymous headless bloqué HTTP 403 ; pas de bypass.
- **Cardova** : chemin strict de ventes finales prouvées dans le stack Robot KB/P3 ; durable write séparé et gardé par #210.
- **PriceCharting V5** : guide values uniquement, pas item-level SOLD ; ne pas substituer à des ventes exactes.

## Invariants

- ASK, active auction, disparition et provider outage ne deviennent jamais SOLD ;
- identité incertaine ou microvariante non prouvée reste bloquée ;
- V4 et Robot KB restent séparés (`V4_USE=false`) ;
- aucun durable Cardova write sans autorisation explicite ;
- PR #8 ne doit pas être mergée sans autorisation explicite ;
- aucun achat, bid, checkout ou paiement automatique.

## Prochaine étape

1. Auditer le run naturel `34037829669` dès qu'il termine.
2. Finaliser ce closeout docs avec la preuve exacte du run.
3. Ouvrir la phase current-main **External SOLD Coverage** en réutilisant les lanes existantes, d'abord read-only/Robot KB, sans modifier l'économie V4 tant qu'une source n'a pas finalité + devise + identité + microvariante prouvées.
4. Ne pas contourner COMC/PSA/eBay anti-bot et ne pas augmenter les caps par réflexe.
5. Garder V5 #8 et Cardova durable séparés.
