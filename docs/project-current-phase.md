# Current phase — generic TCGdex source-pinned finish reconciliation

Production `main` au début de la phase : `febe7620818924a9e0d37dbb2b7bff7c8eb57bee` (merge PR #131).

Working branch : `fix/v4-tcgdex-generic-source-finish-proof-20260818`.

## Verified live state

Premier run production post-#131 : `32132889285` — SUCCESS.

- TCGdex `10 attempted | 4 exact | 2 no-match | 4 ambiguous | 0 error` ;
- PokeTrace `1 attempted | 0 exact | 1 no-match` ;
- Toxtricity `181/172`, `S12a: VSTAR Universe`, JA : candidat PokeTrace exact macro retrouvé mais rejet `PROVIDER_ONLY_FINISH_UNPROVEN` ;
- projection REST TCGdex observée : `normal=1, holo=0, reverse=0` ;
- catalogue source pinné `tcgdex/cards-database@af33c9ac882e2acfadffaf19e8083aa976d12983`, `data-asia/S/S12a/181.ts` : variante unique `holo` ;
- le même drift avait déjà été prouvé pour Kricketune `S12a/174` ;
- final opportunities `0`, aucun achat/bid/checkout/paiement.

## Root cause

PR #131 corrigeait Kricketune avec un registre exact carte par carte. Le run suivant a immédiatement montré le même drift sur Toxtricity. Continuer à ajouter une entrée par carte créerait un treadmill et ne traiterait pas la classe de panne.

## Current change

Remplacer le registre carte par carte par une réconciliation générique et fail-closed :

1. uniquement après identité TCGdex `EXACT` japonaise ;
2. dériver le chemin du fichier `cards-database` depuis `set_id + localId` déjà prouvés ;
3. lire uniquement le commit upstream immuable déjà utilisé par V4 ;
4. vérifier dans le fichier source l'import du même set exact ;
5. parser uniquement le bloc `variants` et n'accepter que `normal/holo/reverse` ;
6. corriger seulement ces trois booléens quand la source pinnée les prouve ;
7. préserver tous les autres flags/microvariantes TCGdex ;
8. cache process-local + budget réseau borné ; timeout/missing/malformed/budget => aucune correction, fail-closed.

Cette couche ne consulte aucun champ PokeTrace pour choisir la preuve. PokeTrace reste market-only.

## Safety

- aucun fuzzy/substr/traduction comme preuve ;
- identité non EXACT, langue non JA, coordonnées incohérentes ou source inaccessible => aucune correction ;
- un type de variante source inconnu => aucune correction ;
- aucun changement fair value, `max_recommended`, seuil économique, grader/grade ou notification ;
- aucun achat, bid, checkout, paiement ou grading payant ;
- PR #8 reste expérimentale et non mergée.

## Next gate

Tests ciblés + full suite V4, compile/YAML/diff et discovery live read-only. Après merge explicitement autorisé, vérifier un run production où une carte affectée (Toxtricity/Kricketune ou autre drift réel) est évaluée et confirmer que PokeTrace n'est plus bloqué par le faux finish REST.
