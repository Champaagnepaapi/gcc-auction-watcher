# Robot Pokémon / GCC Auction Watcher — phase courante

État re-vérifié le **3 septembre 2026** après #237 et #238/#239. Le code/Git/GitHub live reste l'autorité ; re-vérifier le HEAD avant toute action importante.

## Autorité

```text
V4 production branch             main
V4 runtime production            0cab2f3868e80c7c0ed9e6829e44123a2ecd3005 / #238/#239 MERGED
V4 run registry                  issue #235 ACTIVE / issue #1 archive / #237 MERGED
eBay worker bulk text            validated head 90741ac0eaca42f90a6bc7fca816d347aaccafeb
Auction recovery capacity        #229/#231 MERGED / adaptive sizing / hard cap 250
Auction order hardening          #211/#212 MERGED
Future-start auction guard       #220 MERGED / 6a33ac33faa324f0fc1c6124fbb49bd736382b75
TCGdex transport resilience      #216/#217 MERGED / 03824158ac899cf142199c42d4525386a573bc15
TCGdex outage fallback           #222/#224 MERGED / 0be4dca95513e36f4e407ef7bac361fe488c1d36
V5                               PR #8 / OPEN / DRAFT / NON MERGED
Robot KB durable                 PostgreSQL local Mac / séparé de V4 / V4_USE=false
Neon                             writers automatiques OFF / rollback manuel
```

## Phase terminée — registre Main Scanner #235

Issue #1 avait dépassé la limite GitHub de 2500 commentaires : le scan V4 finissait correctement mais l'étape d'ajout du commentaire renvoyait HTTP 403, donnant un faux run rouge.

#237 a déplacé uniquement la cible d'archivage vers l'issue #235. Issue #1 reste l'archive historique.

Preuve naturelle :

```text
run                              33741053547
head                             9fac4bd5cd8211731ee7eaf21bd0302e71fa3a88
workflow conclusion              SUCCESS
scan_exit_code                   0
registry step                    SUCCESS / issue #235
auction scope                    COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS
auction rows / timers            24 / 24
auction fallback                 false
```

Aucune sémantique discovery/identité/valorisation/provider/notification n'a changé.

## Phase runtime — eBay bulk text #238/#239

Problème observé naturellement avant fix : eBay public continuait à provoquer des hard timeouts de 30 s dans le worker enfant isolé, puis le breaker du run sautait les appels restants. La baseline immédiatement pré-merge `33741053547` avait `eBay attempted=16 / insufficient=7 / unavailable=9 / errors=9`, backlog externe `1976`.

Correction :

```text
surface                          li.s-item visible text
nouveau chemin                   un all_inner_texts() bulk par locator
fallback                         nth(i).inner_text() historique si nécessaire
worker isolation                 inchangée
hard timeout / breaker            inchangés
query / parsing SOLD             inchangés
identity/economics/budgets/ntfy  inchangés
```

Validation exacte :

```text
head                             90741ac0eaca42f90a6bc7fca816d347aaccafeb
run                              33650958804 SUCCESS
suite V4                         875 PASS / 2 skipped
compile / YAML / diff-check      PASS
read-only live auction compare   PASS
comparison                       effective=80 / legacy=80 / legacy_only=0 / unresolved=0
production merge                 0cab2f3868e80c7c0ed9e6829e44123a2ecd3005
Fast Lane post-merge             33741652374 SUCCESS
```

Le Ready toggle de #238 a échoué sur le bug GraphQL `fullDatabaseId`; #239 a servi de miroir non-draft au même head exact. GitHub marque les deux PRs comme mergées vers le même merge commit.

### Preuve Main Scanner post-#239

**Encore en attente au moment de ce closeout.** Aucun Main Scanner naturel sur `main@0cab2f...` n'était encore disponible. Ne pas en déclencher un manuellement juste pour fabriquer la preuve.

Le benchmark public #234 reste inconclusif : eBay n'avait exposé aucun `li.s-item` au runner, donc aucune amélioration live de latence/couverture ne doit être revendiquée avant le premier run naturel.

## Invariants inchangés

- #211/#212 + #229/#231 restent l'autorité discovery/recovery auction ;
- #220 future-start reste actif ; premier cas positif réel toujours à observer naturellement ;
- TCGdex #216/#217 + #222/#224 restent stricts/fail-closed ;
- eBay/PSA/provider errors restent fail-visible ;
- `EXTERNAL_PENDING` ne doit pas être forcé par hausse opportuniste de caps ;
- identité/grade/langue/microvariant incompatibles ne sont jamais mélangés ;
- ASK/current auction/disappearance != SOLD ;
- Robot KB reste séparé ; aucun durable write Cardova sans autorisation explicite ;
- PR #8 / V5 reste expérimentale et non mergée ;
- aucun achat, bid, checkout ou paiement automatique.

## Prochaine étape

1. Attendre le premier Main Scanner naturel exact `main@0cab2f3868e8...`.
2. Comparer eBay aux baselines : hard timeouts, résultats utilisables, breaker, durée totale et backlog `EXTERNAL_PENDING`.
3. N'attribuer un gain à #239 que si le live naturel le montre réellement.
4. Continuer d'observer le premier cas future-start réellement exclu et la santé PSA.
5. Garder Robot KB/Cardova durable et V5 séparés.
