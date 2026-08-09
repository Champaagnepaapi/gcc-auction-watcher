# GCC Auction Watcher — Cloud GitHub Actions

Cette version tourne dans GitHub Actions : **aucun Mac ne doit rester allumé**.

## Réglage actuel

- GCC Marketplace : prix fixes et enchères (enchères à **60 minutes maximum**)
- cartes Pokémon uniquement, hors boosters/packs/accessoires
- prix courant : **10 à 100 €**
- décote minimale : **30 %**, relevée automatiquement lorsque les comparables sont faibles
- scan : **toutes les 10 minutes, 24/7**
- notification : **ntfy sur iPhone**
- aucun achat ni aucune enchère automatique

## Installation la plus simple

### 1. Créer un repo GitHub

Sur GitHub, crée un nouveau repository, de préférence **public** si tu veux éviter de consommer le quota Actions d'un repo privé à haute fréquence.

Décompresse ce dossier puis, depuis Terminal :

```bash
git init
git add .
git commit -m "GCC auction watcher"
git branch -M main
git remote add origin URL_DU_REPO_GITHUB
git push -u origin main
```

Tu peux aussi téléverser les fichiers depuis l'interface GitHub si tu préfères éviter Git.

### 2. Configurer ntfy

Sur l'iPhone :

1. installer **ntfy** ;
2. s'abonner à un topic long et aléatoire, par exemple `gcc-...` ;
3. ne pas publier ce nom de topic.

Sur GitHub :

**Repository → Settings → Secrets and variables → Actions → New repository secret**

Nom :

```text
NTFY_TOPIC
```

Valeur : le nom exact du topic choisi dans ntfy.

Le topic n'est donc pas enregistré dans le code public.

### 3. Autoriser GitHub Actions

Ouvre l'onglet **Actions** du repository. Si GitHub demande d'activer les workflows, active-les.

Le workflow `.github/workflows/watcher.yml` démarrera automatiquement toutes les 10 minutes.

Pour tester immédiatement :

**Actions → GCC Auction Watcher → Run workflow**.

### 4. Vérifier le résultat

Ouvre une exécution dans l'onglet Actions. Le log doit notamment afficher :

```text
Ventes détectées: ...
Lots <= 100 €: ...
Opportunités validées: ...
```

Si une opportunité dépasse le seuil, une notification ntfy est envoyée à l'iPhone.

## Important : fréquence GitHub

GitHub accepte les workflows planifiés jusqu'à une fréquence minimale de 5 minutes, mais les tâches planifiées ne constituent pas un ordonnanceur temps réel : une exécution peut être retardée en période de charge.

J'ai volontairement utilisé les minutes `03,13,23,33,43,53` plutôt que `00,10,20...` afin d'éviter les pics typiques autour du début de l'heure.

## État / anti-spam

GitHub Actions utilise des machines éphémères. Le workflow sauvegarde donc `state.json` dans le cache Actions et restaure l'état au prochain scan. Les anciens fichiers d'état restent compatibles.

Une opportunité déjà signalée n'est renotifiée que si son prix baisse d'au moins 10 %, si sa décote gagne au moins 5 points, ou si une enchère franchit un seuil de temps important. Une unique alerte haute priorité est envoyée à cinq minutes ou moins lorsque le prix reste sous le prix maximal conseillé.

## Limite actuelle sur la valorisation

Le scanner GCC fonctionne indépendamment. Le moteur de valorisation est volontairement conservateur : il ne valide une décote que lorsque des comparables exploitables sont visibles.

Les ventes sont normalisées dans un format commun à toutes les sources. Leur pondération de récence est progressive : 1,00 jusqu'à 30 jours, 0,70 à 90 jours, 0,40 à 180 jours et 0,20 à 365 jours, puis au minimum 0,10. Une date inconnue reçoit un poids prudent de 0,45 afin de ne pas supprimer les anciennes données lorsque la liquidité est faible.

Les prix aberrants sont filtrés par MAD (écart absolu médian), avec repli IQR lorsque le MAD est nul. La notification affiche la borne basse, l'estimation centrale, la borne haute, le prix max conseillé, la liquidité, la dispersion, la confiance, la langue, le numéro de carte et la série.

Le prix courant doit rester inférieur ou égal au prix max conseillé, aussi bien pour un prix fixe que pour une enchère. Pour la gradation, une vente de la même société et du même grade constitue le signal principal, même si de nombreuses ventes d'autres graders existent.

En l'absence de vente fiable au grade cible, un grade inférieur de la même société peut produire une voie d'éligibilité distincte **ARBITRAGE GRADE** lorsque son marché robuste est supérieur ou égal au prix actuel. La décote classique n'est alors pas exigée une deuxième fois : le prix max est la borne basse prudente du grade inférieur, la confiance reste faible et la valeur exacte du grade supérieur est explicitement indiquée comme inconnue.

Les ventes d'autres graders restent secondaires et ne peuvent créer seules une estimation achetable. Elles ne deviennent utilisables qu'après normalisation par un ratio empirique possédant assez d'observations et des sources reconnues; aucun ratio de valeur inter-grader n'est appliqué par défaut.

La recherche eBay publique reste un fallback à échec rapide. Le format commun est prêt à recevoir l'eBay Developer API et PSA Auction Prices Realized sans modifier le moteur statistique.

Deux budgets eBay indépendants évitent toute ambiguïté : `EBAY_MAX_QUERIES_PER_CARD` limite les reformulations pour une carte et `EBAY_MAX_CARDS_PER_RUN` limite le nombre d'opportunités contrôlées pendant un scan.

## Modifier les seuils

Dans `.github/workflows/watcher.yml` :

```yaml
MAX_PRICE_EUR: '100'
MIN_DISCOUNT_PCT: '30'
EBAY_MAX_QUERIES_PER_CARD: '2'
EBAY_MAX_CARDS_PER_RUN: '2'
```

Pour un scan toutes les 5 minutes :

```yaml
- cron: '3/5 * * * *'
```

Le réglage 10 minutes est préférable au départ pour limiter les requêtes inutiles sur GCC.
