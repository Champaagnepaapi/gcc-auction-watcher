# CA → PSA fallback calibration — 35%

Date: 2026-09-07

## Décision

Le fallback de revue manuelle `CA -> PSA` passe de **45% à 35% de haircut**.

Ce n'est pas une conversion de valeur CA=PSA. La lane reste `CROSS-GRADER` et le proxy PSA n'est jamais présenté comme comparable exact.

## Pourquoi

45% était volontairement très conservateur mais risquait de masquer des opportunités réelles avant même la revue manuelle. Le réglage 35% augmente le recall de cette lane, tout en conservant :

- préférence pour un proxy CGC de même grade avant PSA ;
- PriceCharting comme cap conservateur compatible, jamais SOLD ;
- floor de **30% de décote après haircut** avant notification ;
- revue manuelle obligatoire ;
- aucun achat/bid/checkout/paiement automatique.

Exemple de bord : PSA proxy 40 EUR, CA10 à 16 EUR. Avec 35% de haircut, référence revue = 26 EUR et décote = 38.5%, donc alerte de revue. Avec 45%, référence = 22 EUR et décote = 27.3%, donc l'opportunité était silencieusement perdue.

Les anciens cas Glaceon CA10 18 EUR / PSA10 34.37 EUR et Riolu CA10 21 EUR / PSA10 36.14 EUR restent sous le floor 30% après haircut 35% et doivent rester supprimés par les tests de régression.

## Recalibration future

Ce 35% est un réglage opérationnel de recall. Si la production génère trop de faux positifs CA, le haircut pourra être remonté sur preuve empirique ; s'il reste trop restrictif, il pourra être réévalué sans modifier les invariants d'identité ou de preuve.
