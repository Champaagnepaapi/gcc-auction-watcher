# Robot Pokémon / GCC Auction Watcher — inventaire des branches

État pertinent re-vérifié le **6 septembre 2026** après les merges production #254/#255. GitHub live reste l'autorité.

```text
V4 production                     main / 9d3bb1b84d22c1534c24d7c58c5897ecce4b817f
#255 source                        v4-external-fair-value-authority-20260906 / MERGED
#254 source                        fix/v4-ebay-bounded-structured-salvage-20260906 / MERGED
#253 source                        fix/v4-ebay-body-timeout-structured-items-20260905 / MERGED
Closeout courant                   docs/post-255-external-fv-closeout-20260906 / DOCS ONLY
P3 durable                         agent/p3-postgres-durable-shadow / séparé de main
V5 expérimentale                  agent/v5-poketrace-cardmarket-market-data / PR #8 OPEN DRAFT
```

## Autorités production récentes

- `v4-external-fair-value-authority-20260906` — #255, head validé `e886c649eea8633d39585aabca8fff0b58be4324`, merge production `9d3bb1b84d22c1534c24d7c58c5897ecce4b817f` ;
- `fix/v4-ebay-bounded-structured-salvage-20260906` — #254, head validé `fbb7041f9fc44c338b102ec7325a6d6316f1e529`, merge production `00e5502fb15c9a89d67a55b70cd566099911bcdb` ;
- `fix/v4-ebay-body-timeout-structured-items-20260905` — #253, head validé `4ced75070cc274abf99ea59f7995d356cbb6dd77`, merge production `23e8e9904072d986e24d2a8fbccaa87568851f69` ;
- lignée #250/#251/#252 — diagnostics/body fallback/parent summary eBay, déjà en production avant #253 ;
- #247/#245/#243/#242/#238/#239/#237/#229/#231/#224/#217/#220/#214/#211/#212 restent autorités historiques de leurs capacités respectives.

## Branche de closeout actuelle

`docs/post-255-external-fv-closeout-20260906` est créée depuis l'exact production `9d3bb1...`. Elle ne doit contenir que documentation/handoff ; aucun runtime, workflow économique, provider, Robot KB durable ou V5 change.

## Anciennes branches eBay — provenance, ne pas réactiver directement

- #226/#228/#233 : superseded par #238/#239 ;
- #234 : validation-only/inconclusive, do not merge ;
- #248 : ancien diagnostic navigation timeout, antérieur à production #250 ;
- anciennes branches de validation/mirror gardent leur valeur de provenance mais ne sont pas des candidats de merge.

## Robot KB / P3 / Cardova

- `agent/p3-postgres-durable-shadow` reste séparée de `main` ;
- #207 est mergée uniquement dans cette lignée P3 ;
- Cardova #199/#204/#205/#206/#208/#209/#210 reste un stack séparé ;
- #210 prépare un write durable gardé, aucune exécution implicite ;
- aucune branche P3/Cardova ne doit être fusionnée dans V4 par housekeeping.

## External SOLD research existant

Réutiliser les branches/PR historiques avant tout nouveau resolver :
- #192 eBay completed benchmark ;
- #193/#195 corroborated sale import/batch ;
- #196 PSA corroboration local Mac ;
- #197 Fanatics PAID history ;
- #198 COMC public history diagnostic ;
- #199+ Cardova SOLD stack.

Ces branches ne sont pas des autorités V4 production ; elles servent de provenance et de code déjà testé à porter proprement sur current-main si une phase le justifie.

## V5

- `agent/v5-poketrace-cardmarket-market-data` — PR #8, OPEN/DRAFT/NON-MERGED ;
- non mergeable au snapshot courant ;
- ne jamais merger dans `main` sans autorisation explicite utilisateur ;
- PriceCharting V5 reste guide-value expérimental, pas item-level SOLD.

## Cleanup

Le nombre total de branches distantes n'a pas été recalculé exhaustivement pendant ce closeout. Ne pas annoncer un compteur ancien comme courant.

Toute suppression exige : inventaire distant, PR/supersession, atteignabilité SHA, références workflow, fichiers/tests/docs uniques, puis autorisation explicite. **Aucune branche n'est supprimée par ce closeout.**
