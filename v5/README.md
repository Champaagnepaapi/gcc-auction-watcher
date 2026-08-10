# GCC Watcher V5 — prototype RAW read-only

Cette V5 est un prototype autonome. Elle n'importe pas `watcher.py`, ne touche
pas au workflow V4 et ne contient aucune route d'achat, d'enchere, d'Order API
ou de checkout.

## Architecture

- `models.py` : identite de carte, annonce eBay, pre-grade, valeurs, couts et diagnostic.
- `ebay.py` : OAuth client-credentials et Browse API eBay officielle en lecture seule.
- `grading.py` : interface `GradeAssessmentProvider`, adaptateur CardGrader.AI et distributions prudentes.
- `valuation.py` : ancien calcul d'EV probabiliste du prototype.
- `market_values/` : fournisseurs, provenance, agregation, couts et prefiltre
  economique non probabiliste avant CardGrader.
- `scanner.py` : garde-fous, classement et sortie diagnostique.
- `../tests_v5/` : fixtures et tests sans reseau.

## Barriere CardGrader.AI

`POST https://cardgrader.ai/v1/scans` consomme des credits. L'adaptateur leve
`PaidCallNotAuthorized` avant tout acces reseau tant que
`CARDGRADER_V5_ALLOW_PAID_CALLS` n'est pas explicitement positionne a `true`.
Le prototype ne lance aucun scan de lui-meme.

Le pipeline est explicitement separe en deux niveaux :

1. `cheap_filter` verifie RAW, prix, identite, couts, valeurs par grade,
   preuves PSA et upside maximal plausible ; il n'appelle jamais le provider
   de grading.
2. `scan_and_rank` classe les candidats d'abord sur le resultat PSA9, puis
   PSA10, et n'envoie au grading visuel que les premiers dans la limite de
   `RAW_MAX_PAID_GRADINGS_PER_RUN`.

Ce quota vaut `0` par defaut. Meme avec un quota positif, le second verrou
`CARDGRADER_V5_ALLOW_PAID_CALLS=false` bloque toujours le POST payant.

Le grade retourne reste une prediction. Les sous-grades, la confiance et les
problemes sont conserves tels que fournis. Une qualite d'image basse ou inconnue
provoque un rejet sur. Le recto et le verso doivent etre designes explicitement
dans `GradeImagePair`.

## eBay RAW structure

La recherche Browse utilise `category_ids` et un `aspect_filter` RAW configures
pour la categorie et la marketplace choisies. Chaque resultat est ensuite lu
avec `GET /buy/browse/v1/item/{item_id}` et revalide via `localizedAspects`.
Le mot « RAW » dans un titre n'est jamais une preuve suffisante.

L'API eBay ne donne pas de role semantique aux images additionnelles. La V5 ne
suppose donc jamais que la deuxieme photo est le verso. Un recto et une identite
exploitables suffisent desormais a poursuivre la valorisation economique. Un
verso absent ajoute `GRADING_VISUAL_CONFIDENCE_REDUCED`; il reste bloquant au
moment d'un eventuel grading visuel, jamais avant l'analyse economique.

Copier les noms de variables de `.env.example` dans l'environnement. L'ID de
categorie et les libelles/valeurs de l'aspect RAW restent configurables car ils
dependent de la marketplace et de la taxonomie eBay active.

## Valeurs et couts

`MarketDataProvider` retourne des valeurs distinctes pour RAW, PSA 8, PSA 9,
PSA 10 et PSA 7 ou moins. Une valeur manquante n'est jamais remplacee par un
autre grade, zero ou une extrapolation. PSA 9 et PSA 10 exigent aussi un nombre
minimum de comparables.

Les couts sont fournis par `CostInputs` ou `costs_from_env`. Une variable absente
reste `None`, donc bloquante ; pour representer un cout nul, il faut saisir `0`.
Aucune conversion de devise implicite n'est effectuee.

`EV nette` designe ici le produit de revente espere apres frais de vente,
grading et couts operationnels, avant prix d'acquisition et livraison d'achat.
`Profit EV` retranche ensuite ces deux couts d'acquisition. Le ROI utilise la
totalite du capital et des couts explicites.

Un candidat est rejete avec `PSA10_DEPENDENT` s'il devient deficitaire en PSA 9
ou si la part du PSA 10 dans l'EV brute depasse le seuil configure.

## Valorisation de marche V5

`PRICECHARTING_ENABLED=false` par defaut garantit qu'aucun appel PriceCharting
n'est emis. L'adaptateur officiel recherche d'abord `/api/products`, exige un
match structure unique et explique, puis lit `/api/product`. Les prix en cents
sont mappes sans extrapolation : raw, grade 8/8,5 generique, grade 9 generique
et PSA 10. Les grades generiques ne sont jamais presentes comme PSA 8 ou PSA 9.

Les prix demandes actifs eBay ne fournissent que des statistiques secondaires
de liquidite en memoire. Ils ne peuvent jamais suffire a autoriser CardGrader
ou une decision d'achat. Marketplace Insights reste une interface desactivee,
et PSA Sales reste `UNAVAILABLE` sans scraping, navigateur headless ou
contournement Cloudflare/CAPTCHA.

Le modele de couts ne remplace aucune variable absente par zero. Le prefiltre
calcule les profits et ROI raw, grade 8 generique, grade 9 generique et PSA 10,
puis emet notamment `RAW_ARBITRAGE`, `GRADE9_PROFITABLE`, `PSA10_DEPENDENT` ou
`ECONOMIC_REJECT_EVEN_PSA10`. Aucune probabilite de grade n'est utilisee a ce
stade et CardGrader reste verrouille.

## Prix RAW

`RAW_MIN_PRICE_EUR` vaut `0` par defaut et accepte donc 0,50 €, 1 €, 2 € ou
5 €. `RAW_MAX_PRICE_EUR` est independant et facultatif. La V5 ne lit jamais
`MIN_PRICE_EUR` ni `MAX_PRICE_EUR` de V4.

Une carte bon marche n'est pas automatiquement gradable. Avant toute analyse
visuelle, son resultat net maximal en PSA10 et son ROI maximal doivent atteindre
`RAW_MIN_PLAUSIBLE_PROFIT_EUR` et `RAW_MIN_PLAUSIBLE_ROI_PERCENT`. Les calculs
incluent achat, livraison, frais acheteur, grading, livraison grading, frais de
vente et autres couts configures.

Le diagnostic final montre le cout total avec grading, les resultats nets PSA10,
PSA9 et PSA8, l'EV probabiliste et le break-even P(PSA10). Une perte en PSA9
classe explicitement le signal comme `speculatif / PSA10_DEPENDENT`.

## Verification hors ligne

```bash
PYTHONPYCACHEPREFIX=/tmp/gcc-v5-pycache \
  python3 -m unittest discover -s tests_v5 -v
```

Les tests injectent des providers et reponses HTTP factices. Ils ne contactent
ni eBay ni CardGrader.AI et ne consomment aucun credit.
