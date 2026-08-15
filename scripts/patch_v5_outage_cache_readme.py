from pathlib import Path

path = Path("README.md")
text = path.read_text(encoding="utf-8")

start_marker = "Head V5 expérimental actuellement validé:\n"
end_marker = (
    "Les PR #75/#76/#77/#78/#79/#80/#84 n’ont pas mergé PR #8. "
    "Les PR #81/#82 ont été mergées **dans la branche V5 expérimentale uniquement**, "
    "jamais dans `main`.\n"
)

if text.count(start_marker) != 1:
    raise SystemExit(f"unexpected start marker count: {text.count(start_marker)}")
if text.count(end_marker) != 1:
    raise SystemExit(f"unexpected end marker count: {text.count(end_marker)}")

start = text.index(start_marker)
end = text.index(end_marker, start) + len(end_marker)

replacement = """Head V5 expérimental actuellement validé:\n\n```text\ndbbe60f03bdb4d95a82f86d72d4241623cfaf877\n```\n\nRègles :\n\n- aucune intégration dans `main` sans autorisation explicite utilisateur ;\n- identité normale : TCGdex exact / unicité déterministe ;\n- PokeTrace reste principalement provider marché/prix ; les recherches PokeTrace de routine pour fabriquer l’identité sont désactivées ;\n- bridge set déterministe seulement ;\n- microvariantes/First Edition/finish fail-closed ;\n- pas d’achat/bid/checkout/CardGrader automatique ;\n- V4, V5 et Robot KB restent techniquement séparés.\n\n## Observabilité identité détaillée — PR #81 + CI offline PR #82\n\nPR #82 a ajouté à la branche V5 un workflow `V5 Offline Validation` sans secrets/providers, destiné aux PR enfants V5. Il exécute la suite `tests_v5`, `compileall v5` et `git diff --check` sans live.\n\nPR #81 a porté la partie utile de l’ancien patch local d’observabilité sur la V5 actuelle, **sans réintroduire son ancienne logique de microvariantes** :\n\n- diagnostics TCGdex/Pokémon TCG par identité ;\n- diagnostics PokeTrace par stratégie, compteurs de candidats et exemples bornés de raisons de rejet ;\n- diagnostic visuel passif avec score/marge/seuils ;\n- JSON structuré par annonce unresolved / blocked ;\n- le `VariantDiagnostic` courant est sérialisé tel quel : l’overlay ne décide pas à la place des gates actuels ;\n- les wrappers appellent les resolvers courants via `super()` et ne changent ni matching, ni seuils, ni valuation ;\n- metadata provider seule ne devient jamais une preuve listing ni un motif de `SINGLE_COMPATIBLE`.\n\nValidation offline PR #81 : run `31898349431`, job `95045035673` — **569/569 tests V5 PASS**, compile/diff PASS, 0 secret commercial/provider injecté.\n\n## PokeTrace market-only + emergency TCGdex — PR #85 / PR #88\n\nPR #85 a supprimé PokeTrace du chemin normal de reconnaissance : TCGdex/catalogue reste l’autorité d’identité, et PokeTrace reste utilisé pour le marché/prix.\n\nPR #88 a ensuite ajouté un secours strict **uniquement après vraie panne technique TCGdex** et le cache Robot KB/Neon :\n\n```text\nTCGdex live\n  -> si panne technique seulement : Robot KB / Neon, identité TCGdex déjà prouvée\n  -> si cache miss/indisponible : Pokémon TCG API catalogue\n  -> si toujours non résolu et panne TCGdex éligible : PokeTrace emergency-only\n  -> sinon fail-closed\n```\n\nRègles emergency :\n\n- panne éligible : transport, JSON invalide, HTTP 408/425/429/5xx ;\n- `CLEAN_NO_MATCH`, 404 et autres 4xx non transitoires n’ouvrent **jamais** Robot KB/PokeTrace emergency ;\n- PokeTrace emergency garde le matching strict existant, ambiguïté = blocage ;\n- budget par défaut : max 5 identités/run, clamp dur 0..10 ;\n- runtime PokeTrace emergency isolé : aucune réponse identité ne prime/alias les caches marché ;\n- Robot KB cache sur langue + nom exact + set exact + numéro local, dénominateur vérifié lorsqu’il est fourni ;\n- plusieurs identités courantes compatibles => `AMBIGUOUS` ;\n- metadata variants du cache ne prouve jamais édition/finish/microvariante ;\n- erreur DB/cache => fallback Pokémon TCG API, jamais crash/faux match ;\n- un succès TCGdex exact peut alimenter le cache ; un échec d’écriture cache n’invalide jamais le succès live.\n\nRobot KB / Neon principal : migration cache appliquée le **16 août 2026**, migration ID `4603e681-2d97-4441-b248-103c7dd3c93a`. Le cache part vide et se remplit uniquement avec des identités TCGdex exactes prouvées.\n\nValidation PR #88 :\n\n```text\nrun 31913172878\njob 95081167254\n```\n\nRésultat :\n\n- **585/585 tests V5 PASS** ;\n- `compileall v5` PASS ;\n- `git diff --check` PASS ;\n- secrets commerciaux/providers injectés : **0** ;\n- aucun live V5 lancé pendant la phase ;\n- aucun achat, bid, checkout ou paiement.\n\nBenchmarks fallback identité :\n\n- PokemonPriceTracker : **16/18** macro exactes sur le panel, 2 vintage laissées ambiguës ;\n- tcgapi.dev : **3/18** macro exactes, langue non prouvée ;\n- JustTCG : **0/20** exact sur le benchmark corrigé set-aware.\n\nPokemonPriceTracker reste le meilleur candidat de fallback macro supplémentaire à ce stade, mais n’est pas promu comme autorité microvariante sans preuve catalogue déterministe.\n\nLes PR #75/#76/#77/#78/#79/#80/#84 n’ont pas mergé PR #8. Les PR #81/#82/#85/#88 ont été mergées **dans la branche V5 expérimentale uniquement**, jamais dans `main`.\n"""

updated = text[:start] + replacement + text[end:]
if updated == text:
    raise SystemExit("README replacement produced no change")
path.write_text(updated, encoding="utf-8")
print("README V5 handoff updated with one bounded replacement")
