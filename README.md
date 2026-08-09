# GCC Auction Watcher

La version recommandée est maintenant la **version cloud GitHub Actions**, qui ne nécessite aucun Mac allumé.

➡️ Lis **README_CLOUD.md** pour l'installation.

Le fichier `watcher.py` scanne les prix fixes et les enchères GCC, conserve uniquement les cartes Pokémon entre 10 et 100 € (enchères à 60 minutes maximum), puis envoie une notification ntfy lorsqu'une opportunité suffisamment étayée est détectée.

La valorisation utilise une médiane pondérée par récence, un filtre robuste MAD/IQR, une fourchette prudente et un seuil de décote adaptatif (plancher 30 %). Prix fixes et enchères doivent rester sous le prix maximal conseillé; une enchère admissible peut recevoir une alerte unique dans les cinq dernières minutes.

Un grade supérieur proposé au niveau du marché robuste du grade inférieur de la même société peut être signalé comme **ARBITRAGE GRADE**, sans inventer la valeur du grade supérieur. Les ventes d'autres sociétés de grading ne créent aucune valeur achetable sans ratio empirique suffisamment documenté.

Le script ne passe jamais d'enchère et n'effectue aucun achat.
