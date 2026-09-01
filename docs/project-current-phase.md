# Robot Pokémon / GCC Auction Watcher — phase courante

État re-vérifié le **1 septembre 2026** après #227 et #229/#231. Le code/Git/GitHub live reste l'autorité ; re-vérifier le HEAD avant toute action importante.

## Autorité

```text
V4 production branch             main
V4 runtime production            b6a7c834264c062ea81b64c714e6916aa8bfe9f2 / #229/#231 MERGED
Auction recovery capacity        adaptive sizing / hard cap 250
Auction order hardening          #211/#212 MERGED
Future-start auction guard       #220 MERGED / 6a33ac33faa324f0fc1c6124fbb49bd736382b75
TCGdex transport resilience      #216/#217 MERGED / 03824158ac899cf142199c42d4525386a573bc15
TCGdex outage fallback           #222/#224 MERGED / 0be4dca95513e36f4e407ef7bac361fe488c1d36
V5                               PR #8 / OPEN / DRAFT / NON MERGED
Robot KB durable                 PostgreSQL local Mac / séparé de V4 / V4_USE=false
Neon                             writers automatiques OFF / rollback manuel
```

## Phase terminée — #229/#231 auction recovery capacity

Le problème n'était pas le cap économique 360 : pendant une dérive d'ordre GCC, la récupération exhaustive #211 pouvait simplement dépasser son ancien safety bound de **100 pages** parce que l'univers `AUCTION + ON_SALE` avait grandi au-delà de 10 000 lignes.

Preuves naturelles pré-fix :

- `33547948642` : order drift → recovery → safety limit 100 pages → fallback legacy ; 39/39 auctions ≤60 min économiquement tentées, 0 différée par cap ;
- `33548929050` : fast path voisin sain, `COMPLETE`, 96 rows / 28 ≤60 min, fallback false ;
- `33549911988` : même safety-limit recovery → fallback ; 14/14 ≤60 min tentées, 0 différée par cap.

Correction production :

```text
recovery budget                  ceil(api_total / page_size) + 2
minimum                          ancien bound
hard ceiling                     250 pages
api_total                        sizing-only ; jamais preuve COMPLETE
preuve COMPLETE                  vraie exhaustion API / nextPage absent
fast path                        inchangé
auction economic cap             360 inchangé
```

Pour ~15 049 rows à 100/page, la capacité devient 153 pages au lieu de 100.

Validation :

```text
exact head/tree                  f81f81d1cf349a298d07867e9750704a9ea0c2bd / 0170d41c548878f4a4a77b7662f0b0a6e0f002c2
#229 own validation              33563203801 SUCCESS
#231 merge-mirror validation     33563438585 SUCCESS
complete V4 suite                PASS
compile / YAML / diff-check      PASS
read-only live compare           api_primary_complete=true / legacy_only=0 / unresolved=0
production merge                 b6a7c834264c062ea81b64c714e6916aa8bfe9f2
```

Le Ready toggle de #229 a échoué sur le bug GraphQL GitHub `fullDatabaseId`; #231 a donc été créé comme miroir non-draft du **même SHA/tree** et validé avant merge. GitHub marque ensuite #229 et #231 comme mergées vers le même merge production.

## Preuve production naturelle post-#231

**Pas encore disponible au moment de ce closeout.** Le registre #1 ne contient encore aucun run exact sur `main@b6a7c834...`. Le dernier run enregistré avant le merge reste sur l'ancien runtime.

Ne pas lancer le Main Scanner manuellement juste pour fabriquer la preuve. Attendre le scheduler externe et inspecter le premier run naturel, idéalement le premier avec vraie dérive d'ordre.

## Invariants inchangés

- #211/#212 restent l'autorité de discovery/pagination ;
- #220 future-start reste actif et le premier cas positif réel reste à observer naturellement ;
- TCGdex #216/#217 + #222/#224 restent stricts/fail-closed ;
- eBay/PSA/provider errors restent fail-visible ;
- `EXTERNAL_PENDING` ne doit pas être forcé par hausse opportuniste de caps ;
- identité/grade/langue/microvariant incompatibles ne sont jamais mélangés ;
- ASK/current auction/disappearance != SOLD ;
- Robot KB reste séparé ; aucun durable write Cardova sans autorisation explicite ;
- PR #8 / V5 reste expérimentale et non mergée ;
- aucun achat, bid, checkout ou paiement automatique.

## Prochaine étape

1. Attendre un run naturel `main@b6a7c834...`.
2. Si l'ordre GCC dérive, vérifier que le recovery adaptatif peut dépasser 100 pages et atteint l'épuisement réel ou reste fail-closed.
3. Continuer d'observer le premier cas future-start réellement exclu.
4. Continuer d'observer TCGdex/eBay/PSA et le backlog `EXTERNAL_PENDING` sans relâcher les preuves.
5. Garder Robot KB/Cardova durable et V5 séparés.
