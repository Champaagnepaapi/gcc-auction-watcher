# Focused slab hardening handoff

Temporary handoff; canonical README will absorb this before merge.

- Runtime priority: PSA / PCA / CCC cert-first.
- CCC live cert `544340143` resolves to grade 9 from GitHub Actions.
- PSA and PCA official pages currently return unavailable/challenge from GitHub Actions; no anti-bot bypass.
- Cert unavailable -> focused OCR fallback only for PSA/PCA/CCC.
- OCR ROI is grader-specific top/right label area; subgrade lines are excluded.
- OCR requires 2-pass consensus after Pillow preprocessing.
- Live focused OCR benchmark run `31868591602`: 24 slabs, 4 exact, 0 wrong, 12 ambiguous, 8 unavailable; 100% precision among accepted reads.
- IMAGE_ONLY mismatches are manual-review leads only: they never block or rewrite normal V4 valuation.
- Negative OFFICIAL_CERT mismatch remains a safety gate.
- V5 PR #8 untouched; future V5 slab verification should prioritize the same PSA/PCA/CCC trio unless user requests broader scope.
