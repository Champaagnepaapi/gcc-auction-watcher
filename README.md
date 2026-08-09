# GCC Auction Watcher

La version recommandée est maintenant la **version cloud GitHub Actions**, qui ne nécessite aucun Mac allumé.

➡️ Lis **README_CLOUD.md** pour l'installation.

Le fichier `watcher.py` scanne les enchères GCC, filtre le prix courant à 100 € maximum et envoie des notifications via ntfy lorsqu'une opportunité suffisamment étayée est détectée.

Le script ne passe jamais d'enchère et n'effectue aucun achat.
