# V4 Global Market Live Shadow dispatcher — 16 août 2026

But : rendre visible le bouton GitHub Actions `Run workflow` depuis la branche par défaut, sans porter le code expérimental sur `main`.

- workflow : `.github/workflows/v4-global-live-shadow.yml`
- déclenchement : `workflow_dispatch` manuel uniquement
- permissions : `contents: read`
- aucune persistance de credentials checkout
- ntfy forcé off
- aucune écriture Neon
- aucun achat, bid, checkout, paiement ou grading
- `main` ne contient volontairement pas les scripts shadow : le workflow fail-closed si la branche sélectionnée ne contient pas `v4_global_live_shadow.py`
- `rejection_diagnostics=true` exige `v4_global_rejection_diagnostics.py`, donc la branche prévue est `feat/v4-global-rejection-diagnostics`

Usage prévu :

1. Actions → `V4 Global Market Live Shadow` ;
2. `Run workflow` ;
3. branche `feat/v4-global-rejection-diagnostics` ;
4. `rejection_diagnostics=true` ;
5. lancer.

Cette exposition du dispatcher ne change aucun calcul V4 production et ne merge aucune PR expérimentale.
