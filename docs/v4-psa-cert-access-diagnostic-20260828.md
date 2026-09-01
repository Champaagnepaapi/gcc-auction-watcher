# V4 — PSA cert access diagnostic — 2026-08-28

## Conclusion

La voie `GCC serialNumber -> page publique PSA /cert/{serial}/psa -> Sales of Similar Items` **ne doit pas être branchée dans V4 sur GitHub Actions**.

Le probe réel depuis un runner GitHub-hosted retourne **HTTP 403** sur la page cert PSA, de la même manière que la recherche publique PSA Auction Prices Realized `/auctionprices` déjà observée en production.

Aucun contournement WAF/anti-bot, cookie privé, proxy furtif ou session utilisateur n'est introduit.

## Preuves

Production V4 canonique au début de la phase :

- `main@a4db237cfea1bc916cc6ebbd2b137f754f93afc5` ;
- PR #189 déjà mergée : breaker PSA après HTTP 403/429, sans reclassifier la panne en clean no-match ;
- run production `33156273150` : premier appel PSA APR HTTP 403 puis appels APR restants du run sautés correctement.

Le spool passif `v4-kb-shadow-spool` du run `33156273150` montre que GCC fournit bien `item.serialNumber` pour les listings PSA observés :

- 719 listings PSA examinés dans l'échantillon ;
- 719/719 avec un `serialNumber` structuré ;
- cette donnée constitue une excellente clé d'identité cert, mais ne résout pas à elle seule l'accès aux SOLD PSA.

Un bridge expérimental a été écrit uniquement sur une branche dédiée puis testé hors production. Les 8 tests unitaires ciblés passaient. Un probe one-shot PR-only a ensuite testé la vraie route PSA depuis GitHub Actions.

Validation live :

- PR #190 ;
- workflow `V4 Auction Discovery Validation` ;
- run `33178238059` ;
- head probe `6141d047f05d13cfbf31f9bc8c6fc8653c9db126` ;
- résultat du probe : `status=403`, certificat non visible, `Item Grade` non visible, `Sales of Similar Items` non visible ;
- la CI a échoué uniquement sur ce probe live ; les tests unitaires du bridge étaient verts.

Après cette preuve, le bridge runtime et les tests/probe one-shot ont été retirés de la branche : **aucun code runtime PSA cert n'est proposé au merge**.

## API PSA officielle

Le dépôt contient déjà `.github/workflows/psa-api-diagnostic.yml`, qui utilise l'API officielle PSA avec `PSA_API_TOKEN` pour :

- `GET /publicapi/cert/GetByCertNumber/{cert}` ;
- `GET /publicapi/pop/GetPSASpecPopulation/{specID}`.

La documentation publique PSA actuelle indique que l'API publique documentée sert à la vérification de certification par numéro. Elle ne documente pas d'endpoint fournissant les `Sales of Similar Items`, les prix SOLD ou l'historique APR nécessaire à la valorisation.

Conséquence : l'API officielle peut améliorer/confirmer **l'identité, le grade et éventuellement la population**, mais elle ne remplace pas la preuve de prix SOLD PSA recherchée ici.

## Capacités existantes auditées

Avant de conclure, les routes cert déjà présentes ont été relues :

- `v4_focus_cert_router.py` ;
- `v4_mislisted_cert_router.py` ;
- `v4_mislisted_slab_hunter.py` / infrastructure associée.

La route PSA existante utilise elle aussi la page publique `/cert/{cert}/psa` pour vérifier le grade. Elle ne constitue pas une source SOLD distincte et subit donc le même risque d'accès 403 depuis GitHub Actions.

## Décision

Pour V4 GitHub Actions :

1. garder le breaker #189 ;
2. ne pas traiter le 403 PSA comme un no-match ;
3. ne pas déployer le bridge web cert bloqué ;
4. ne jamais utiliser `PSA Estimate` comme vente ;
5. conserver `serialNumber` comme clé d'identité potentiellement utile pour une future source autorisée ;
6. pour les prix, privilégier les sources exactes réellement accessibles (PokeTrace/PPT selon leur sémantique et leur corrélation, eBay SOLD quand exploitable, ou une future API market-wide autorisée).

PokeTrace/PPT/eBay restent une famille de signal potentiellement corrélée et ne doivent pas être comptés naïvement comme trois marchés indépendants.

## Sécurité / invariants

- aucune modification production ;
- aucune relaxation identité/langue/grader/grade/microvariante ;
- aucun changement de fair value, décote ou `max_recommended` ;
- aucun achat, bid, checkout ou paiement ;
- aucun secret exposé ;
- PR #8/V5 intacte et non mergée.
