from pathlib import Path

path = Path("README.md")
text = path.read_text(encoding="utf-8")

old_head = '''Head V5 expérimental actuellement validé :

```text
dbbe60f03bdb4d95a82f86d72d4241623cfaf877
```
'''
new_head = '''Head V5 expérimental actuellement validé :

```text
bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
```

Ce SHA est le merge **V5-only** de la PR #93. PR #8 reste ouverte/draft et **non mergée dans `main`**.
'''
if text.count(old_head) != 1:
    raise SystemExit(f"unexpected V5 head marker count: {text.count(old_head)}")
text = text.replace(old_head, new_head, 1)

marker = '''Benchmarks fallback identité :

- PokemonPriceTracker : **16/18** macro exactes sur le panel, 2 vintage laissées ambiguës ;
- tcgapi.dev : **3/18** macro exactes, langue non prouvée ;
- JustTCG : **0/20** exact sur le benchmark corrigé set-aware.

PokemonPriceTracker reste le meilleur candidat de fallback macro supplémentaire à ce stade, mais n’est pas promu comme autorité microvariante sans preuve catalogue déterministe.

Les PR #75/#76/#77/#78/#79/#80/#84 n’ont pas mergé PR #8. Les PR #81/#82/#85/#88 ont été mergées **dans la branche V5 expérimentale uniquement**, jamais dans `main`.
'''
replacement = '''## Finish / microvariante post-macro — PR #93

PR #93 a été mergée **uniquement dans la branche V5 expérimentale** :

```text
bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f
```

Feature head validé :

```text
129799cbafdc6ff2306a4370c97f4aa030673e84
```

Changements :

- le retry exact TCGdex d’applicabilité microvariante est maintenant réellement appelé après résolution macro lorsque la preuve catalogue initiale reste inconnue ;
- seule une preuve `TCGDEX_EXACT` peut remplacer l’inconnu sur ce chemin ;
- mapping promo versionné et borné pour les préfixes officiels (`DP/HGSS/BW/XY/SM/SWSH`) avec préfixe également exigé dans le numéro ;
- normalisation déterministe limitée aux familles mappées, par exemple `DP045 -> DP45` ;
- correction sémantique : TCGdex `wPromo` signifie **W-stamp**, pas appartenance générique à une série Promo ; ce champ ne prouve donc ni le statut promo général ni le finish à lui seul ;
- aucun seuil économique, matching fuzzy ou gate de sécurité n’a été relâché.

Validation offline : run `31915971540`, job `95087685592` — **600/600 tests V5 PASS**, compile/diff PASS, 0 secret commercial/provider injecté.

Validation live contrôlée : run `31916052221`, job `95087872111` — SUCCESS ; 17 requêtes TCGdex, 2 hits, 0 `variant-impossible`, 2 écritures Robot KB (1 insert + 1 idempotente), 0 achat/bid/checkout/CardGrader. Neon contient désormais exactement une identité `dpp-DP45` / Charizard G / DP Black Star Promos / `DP45` / EN, sans collision langue/set/numéro.

## Catalog gaps physiques récents — PR #96 en draft

La PR #96 est **offline-validée mais non mergée dans V5**. Elle traite deux catégories qui ne doivent pas être confondues :

- Pokémon TCG Pocket est un produit numérique et doit être rejeté avant le pipeline de cartes physiques ;
- une vraie carte physique récente absente de TCGdex peut être ajoutée à un registre exact, versionné et sourcé, jamais via une règle générique `TCGdex no-match => accept`.

Premier gap exact documenté dans la PR : Magikarp coréen `040/M-P`, `M-P Promotional cards`, 2026, Holo Promo. L’entrée exige nom + numéro imprimé + langue + set/alias borné exact, et toute contradiction ou ambiguïté restante bloque.

PR #96 : head `360ae33a67987e0a981b348e636bd7e2f964667e`, base V5 `bc641dfe64c1cacc912b585d4e86fc3c1bd7d95f`. Validation offline run `31937817636`, job `95142423068` : **611/611 tests V5 PASS**, compile/diff PASS, 0 secret injecté. **Aucune validation live n’est revendiquée pour #96 à ce stade.**

Benchmarks fallback identité :

- PokemonPriceTracker : **16/18** macro exactes sur le panel, 2 vintage laissées ambiguës ;
- tcgapi.dev : **3/18** macro exactes, langue non prouvée ;
- JustTCG : **0/20** exact sur le benchmark corrigé set-aware.

PokemonPriceTracker reste le meilleur candidat de fallback macro supplémentaire à ce stade. Le test shadow live borné a confirmé une bonne capacité de récupération de set mais aussi des catégories trop génériques : il reste donc **shadow-only** et ne peut pas contourner les gates microvariantes.

Les PR #75/#76/#77/#78/#79/#80/#84 n’ont pas mergé PR #8. Les PR #81/#82/#85/#88/#93 ont été mergées **dans la branche V5 expérimentale uniquement**, jamais dans `main`. PR #96 reste draft/non mergée.
'''
if text.count(marker) != 1:
    raise SystemExit(f"unexpected benchmark marker count: {text.count(marker)}")
text = text.replace(marker, replacement, 1)

path.write_text(text, encoding="utf-8")
print("README V5 handoff updated for PR #93 and pending PR #96")
