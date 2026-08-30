# Robot Pokémon / GCC Auction Watcher — phase courante

État re-vérifié le **30 août 2026** après validation live Mac du compose Cardova macro/finish et du fallback No Rarity borné.

## Autorité

```text
V4 production                    main @ b98756c449718845fc1944560fcf61c02586079f
Dernier merge V4                 PR #203 / weekly stability budget
Robot KB                         PostgreSQL local Mac ACTIF
Robot KB P3                      1d06fe33b6fc640657255e15a8d17251aa02b6ce
Cardova #199                     OPEN / DRAFT / NON MERGED
Cardova research head validé     59d006fc7259198f13d957b412bc48e4911c067f
Cardova collector runtime pin    a2f1878186a8850d5a4c4763518a10ecfd16f2fc
Cardova SALES unresolved         244 disponibles
Cardova macro exact              38 read-only
Cardova finish exact             38
Cardova printing exact           5 No Rarity Symbol
Cardova microvariant exact       0
Cardova canonical links          0
V4_USE                           false
V5                               PR #8 OPEN / DRAFT / NON MERGED
```

Le code/Git/GitHub live reste prioritaire. PR #8 ne doit jamais être mergée sans autorisation explicite.

## Cardova paid/completed SOLD

Gate inchangé : `bid_payment_status=5`, `finished=1`, non annulé, non relisté, JPY prouvée, final winning bid positif.

Sémantique : `SALE_TRANSACTION`, `sale_occurred_at = auction_end_at_utc`, `HAMMER_PRICE` JPY. Aucun timestamp de paiement, all-in ou buyer premium fabriqué.

Le snapshot local read-only du 30 août expose **244 `SALE_TRANSACTION` unresolved**. La recherche d'identité ne modifie pas ces lignes et n'écrit aucun lien canonique.

## Macro-identité — 38 exactes

Le compose `robot_kb_cardova_bounded_macro_identity_probe.py` promeut uniquement une ligne dont toute la chaîne suivante est vraie :

- set Cardova exact indépendamment corroboré ;
- nom anglais Cardova ↔ TCGdex exact ;
- valeur numérique cohérente pour cette ligne ;
- une seule carte TCGdex pour ce dexId dans le set corroboré ;
- source TCGdex Asian immuable au commit `af33c9ac882e2acfadffaf19e8083aa976d12983`.

Live :

```text
Basic / PMCG1                    17
neo Gold, Silver... / neo1       10
Jungle / PMCG2                    6
Rocket / PMCG4                    5
TOTAL macro exact                38
provider numeric global claim    false
blocked                          {}
error                            null
```

La preuve est **row-scoped** ; aucune règle universelle « numéro Cardova = dexId » n'est créée.

## Finish — 38 exacts

Le probe `robot_kb_cardova_legacy_macro_finish_probe.py` compose les macros avec la source TCGdex pinnée. Un finish source unique est exact ; un claim `Holo` Cardova ne sert que lorsqu'il est compatible/corroboré. Les tokens opaques ne deviennent pas finish seuls.

Live : `finish_exact=38` sur les 38 macros.

Les axes `edition_applicability`, `special_finish_applicability` et `variant_applicability` restent ouverts ; donc `microvariant_exact=0` et `links=0`.

## No Rarity Symbol — 5 coordonnées exactes seulement

PSA direct reste bloqué depuis le Mac : **5/5 HTTP 403** sur les certs ciblés. Aucun bypass n'est utilisé.

Le fallback `robot_kb_cardova_no_rarity_reviewed_fallback.py` accepte seulement le token Cardova exact `no rarity original print` et un manifest de preuve publique PSA déjà revu, borné à :

- Sandshrew `#027` ;
- Nidorino `#033` ;
- Arcanine `#059` ;
- Machop `#066` ;
- Gastly `#092`.

Live :

```text
manifest entries                  5
reviewed proven                   5
printing exact                    5 = no_rarity_symbol
finish exact                      normal pour les 5
live PSA blocked                  PSA_NO_RARITY_HTTP_403: 5
Cardova cert read                 false
edition exact                     false
No Rarity => First Edition        false
microvariant exact                0
links                             0
blocked                           {}
error                             null
```

Le fallback n'est pas extensible automatiquement à une 6e coordonnée et ne remplace jamais une lecture du cert Cardova.

## Collecteur récurrent local

- front pages + rotation historique ;
- aucun ordre de tri Cardova supposé ;
- readiness retry borné 5000/6500/8000 ms ;
- lock séparé `cardova-sold` ;
- PostgreSQL loopback `robot_pokemon_kb` uniquement ;
- LaunchAgent `com.robotpokemon.kb.cardova-sold` ;
- cadence 02:23 / 08:23 / 14:23 / 20:23 ;
- runtime collector pin `a2f1878186a8850d5a4c4763518a10ecfd16f2fc` ;
- aucun secret dans plist ; credential PostgreSQL lu depuis le Trousseau.

Le dernier cursor collector documenté était page 13, mais **il n'a pas été re-audité pendant cette phase identity**. Ne pas déduire le cursor courant du total 244.

## Validation

Head fonctionnel/research `59d006fc7259198f13d957b412bc48e4911c067f` :

```text
Robot KB local PostgreSQL        run 33333404769 SUCCESS
V4 Auction Discovery             run 33333404817 SUCCESS
V4 Global Market Offline         run 33333404767 encore en cours au handoff
No Rarity fallback tests         7/7 PASS
bounded macro tests              5/5 PASS
legacy macro/finish tests        18/18 PASS
compile/YAML/diff-check          PASS dans Robot KB CI
live Mac read-only               SUCCESS
```

Live Mac final : `unresolved=244`, `selected=244`, `macro_exact=38`, `finish_exact=38`, `printing_exact=5`, `micro_exact=0`, `links=0`, `blocked={}`, `error=null`.

## Prochaine phase

1. Fermer déterministement les axes réellement applicables `edition`, `special_finish`, `variant` sur les 38 macros ; aucune absence de donnée ne devient une valeur par défaut.
2. Garder les 5 No Rarity avec `printing_exact=true` mais `edition_exact=false` tant qu'une preuve distincte n'existe pas.
3. Ne créer aucun canonical link / comparable exact tant que `microvariant_exact=0`.
4. Ne plus retry PSA direct dans cette phase tant que le 403 persiste ; aucun bypass.
5. Laisser le collector Cardova continuer à accumuler les ventes finales et re-auditer séparément son cursor/rotation.
6. Garder `V4_USE=false` et #199 DRAFT/non mergée jusqu'à décision explicite.
7. Garder PR #8 V5 isolée/non mergée.

Aucun achat, bid, offer, checkout ou paiement automatique.
