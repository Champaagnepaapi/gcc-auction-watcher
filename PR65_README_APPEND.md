
---

# PR #65 — PSA/PCA/CCC cert-first + OCR ciblé conservateur

- Branche : `agent/v4-psa-pca-ccc-ocr-hardening`.
- Priorité runtime : **PSA / PCA / CCC** pour les incohérences de slab ; les autres vérificateurs officiels déjà supportés restent disponibles.
- Ordre : **certificat officiel du grader → comparaison grade GCC ↔ grade officiel → OCR ciblé uniquement si le certificat est indisponible/non lisible**.
- CCC : validation live depuis GitHub Actions sur le certificat `544340143` → **grade officiel 9**, alors que des subgrades incluent notamment 9.5 ; le parser ne promeut pas les subgrades.
- PSA : lookup officiel conservé, mais le smoke test GitHub Actions courant retourne `CERT_UNAVAILABLE`; aucun contournement WAF/anti-bot.
- PCA : le site renvoie actuellement une vérification anti-bot à GitHub Actions ; `CERT_UNAVAILABLE`, aucun contournement.
- OCR fallback **uniquement PSA/PCA/CCC** :
  * ROI top-label spécifique par grader (zone droite/haute) ;
  * exclusion explicite `CENTERING/CENTRAGE`, `EDGES/CÔTÉS`, `CORNERS/COINS`, `SURFACE` ;
  * Pillow upscale/contraste/netteté ;
  * trois vues Tesseract et **au moins deux lectures concordantes**.
- Sécurité :
  * `NEGATIVE_GRADE_MISMATCH + OFFICIAL_CERT` = safety gate, opportunité économique bloquée ;
  * `IMAGE_ONLY` positif ou négatif = **manual review seulement**, jamais de changement/blocage de valorisation ;
  * OCR ambigu/illisible = aucune conclusion fabriquée.
- Benchmark OCR read-only `31868591602` / job `94973448924` : 24 slabs (8 PSA, 8 PCA, 8 CCC) → **4 exacts, 0 faux, 12 ambigus, 8 indisponibles** ; précision des lectures acceptées **100 %**, couverture volontairement prudente.
- Diagnostic cert live `31869307027` / job `94975334499` : CCC `544340143` = 9 confirmé ; PSA indisponible depuis Actions ; PCA challenge anti-bot.
- Validation PR #65 initiale : run `31869485436`, job `94975774681` → **490/490 tests PASS**, compile PASS, `git diff --check` PASS, discovery live 49/49 vs legacy, `primary_only=0`, `legacy_only=0`, private failures 0.
- Aucun achat, bid, checkout ou paiement automatique.
- V5 PR #8 reste **inchangée et non mergée**. Pour une future transposition V5, concentrer d’abord le slab mismatch sur PSA/PCA/CCC sauf instruction contraire.
