# GCC Auction Watcher — Cloud GitHub Actions

Cette version tourne dans GitHub Actions : **aucun Mac ne doit rester allumé**.

## Réglage actuel

- GCC Marketplace : enchères uniquement
- prix courant maximal : **100 €**
- décote minimale : **20 %** lorsqu'une estimation fiable est disponible
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

GitHub Actions utilise des machines éphémères. Le workflow sauvegarde donc `.data/state.json` dans le cache Actions et restaure l'état au prochain scan. Cela permet d'éviter de renvoyer exactement la même alerte à chaque exécution.

## Limite actuelle sur la valorisation

Le scanner GCC fonctionne indépendamment. En revanche, le moteur de valorisation est volontairement conservateur : il ne valide aujourd'hui une décote que lorsque des comparables exploitables sont visibles.

La prochaine étape est d'ajouter des comparables externes (ventes réellement réalisées, lorsque l'accès et les conditions d'utilisation de la source le permettent) et une normalisation stricte : carte, set, numéro, langue, grade et société de grading.

## Modifier les seuils

Dans `.github/workflows/watcher.yml` :

```yaml
MAX_PRICE_EUR: '100'
MIN_DISCOUNT_PCT: '20'
```

Pour un scan toutes les 5 minutes :

```yaml
- cron: '3/5 * * * *'
```

Le réglage 10 minutes est préférable au départ pour limiter les requêtes inutiles sur GCC.
