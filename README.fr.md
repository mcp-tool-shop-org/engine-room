<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.md">English</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="app/logo.png" width="400" alt="engine-room">
</p>

<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/engine-room/actions/workflows/ci.yml"><img src="https://github.com/mcp-tool-shop-org/engine-room/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License: MIT"></a>
  <a href="https://mcp-tool-shop-org.github.io/engine-room/"><img src="https://img.shields.io/badge/landing%20page-engine--room-0a7ea4" alt="Landing page"></a>
</p>

Un **outil de provisionnement basé sur des recettes pour les moteurs d'IA locaux.** Parcourez un catalogue de « recettes de moteur » vérifiées et mesurées, choisissez-en une et déployez-la sur votre propre infrastructure GPU. Le processus se déroule en trois étapes : **provisionnement → lancement → mesure**, le tout effectué à la volée, de manière reproductible et validé par rapport à une base de référence de performance réelle.

## Pourquoi ?

Les moteurs d'IA locaux sont extrêmement hétérogènes en termes de déploiement : l'un est construit à partir du code source avec CUDA, le suivant est un conteneur, puis un ensemble portable, et enfin un quantificateur qui écrit un fichier avant de se terminer. Déterminer *quel* moteur utiliser est déjà un problème (une base de connaissances peut le résoudre), mais le véritable défi réside dans la capacité à *le déployer correctement, de manière reproductible et à vérifier qu'il fonctionne*. C'est là que `engine-room` entre en jeu.

## Architecture : deux éléments, une seule interface

`engine-room` représente la moitié « action » d’une division délibérée :

- **Connaissance** : la *recette* vérifiée, documentée et abstraite (ce qui doit être construit, l'ensemble d'outils fixe, les objectifs de base de référence mesurés, les étapes de restauration déclarées). Elle change lorsqu'un moteur en amont est mis à jour. Elle réside dans la base de connaissances.
- **Action** : ce dépôt : résolution d’une recette par rapport à l’infrastructure active, matérialisation, lancement/mesure et restauration sécurisée. Il change lorsque *l’infrastructure* change.

## Obtenir la couche de recette

`engine-room` représente la moitié « action »; il ne fournit pas les recettes elles-mêmes. La moitié « connaissance » est un artefact distinct et vérifié : la base de données de recettes `tensor-engine-knowledge` (`engines.db`), que vous devez spécifier à `er`. Le simple clonage de ce dépôt ne vous donne que l’exécuteur, pas le catalogue.

- **Détectez votre infrastructure** sans base de données de recettes : la commande `er rig` lit uniquement le matériel actif (`nvidia-smi` + variables d'environnement), elle fonctionne donc immédiatement.
- **Spécifiez la base de données de recettes** pour tout le reste (`list` / `show` / `preflight` / `provision`) de deux manières :
- définissez `ER_RECIPES_DB` sur le chemin d'accès à la base de données, ou
- passez `--db <chemin>` avec n'importe quelle commande.
- Si aucune des options n’est définie, `er` recherche `../../readouts/tensor-engine-knowledge/engines.db` par rapport au dépôt. Lorsque la base de données est manquante, vous obtenez un message d’erreur clair (`recipe DB not found: … — set $ER_RECIPES_DB or pass --db`), et non une trace de pile.

La couche de recette représente l'entrée de connaissance fiable (voir [Sécurité / modèle de menace](#security--threat-model)). Obtenez `engines.db` à partir de la distribution `tensor-engine-knowledge`; `engine-room` la lit en **lecture seule** et ne l’écrit jamais.

Une recette est **polymorphe** : quatre types, chacun ayant une forme différente :

| Type | Ce qu'elle fait | Mesuré par |
|------|--------------|-------------|
| `launchable-server` | démarre un serveur de longue durée sur un port | débit (tok/s, it/s) |
| `batch-producer` | s'exécute, écrit un artefact et se termine | qualité de la sortie + temps d'exécution |
| `modifier` | une superposition qui accélère une autre recette | delta mesuré |
| `router-fleet` | un point d'entrée qui redirige vers d'autres recettes | état de chaque composant en amont |

## Reproductible et validé par conception

- **Artefacts fixes et fournis** (un hachage par rapport à un index organisé n’est pas suffisant lorsque l’index supprime la chaîne : le point fixe doit être une copie adressée par son contenu).
- Les **bases de référence mesurées** sont liées au modèle et comportent une bande de compatibilité, de sorte qu'une simple mise à jour du pilote ne les invalide pas.
- Une **porte de contrôle de la correction s’exécute avant toute affirmation sur les performances**, avec une option de configuration par modalité de sortie.
- Chaque **étape irréversible comporte un nom d’annulation** avec un état honnête après la restauration ; les étapes globales nécessitent une approbation humaine explicite.

## État

L'exécuteur est implémenté. La CLI `er` lit la couche de recette et résout une recette par rapport à l’infrastructure active (`rig` / `list` / `show` / `preflight`, toutes sans effets secondaires), et le provisionneur exécute la boucle de réconciliation : **exécution à sec par défaut**, avec un chemin `--execute` configuré qui matérialise les artefacts fixes, lance un serveur local et mesure ses performances par rapport à la base de référence de la recette (`provision` / `teardown` / `status`). Voir [`executor/README.md`](executor/README.md).

La reproductibilité est aujourd'hui honnêtement partielle : les points fixes sont résolus par rapport à un index, et les artefacts non fixés sont acceptés ; le fait de les stocker dans un magasin adressé par son contenu afin que la `reproductibilité` soit *acquise* est **l’objectif n° 1**.

L'interface utilisateur opérateur est fournie sous forme de prototype autonome (données simulées + effets secondaires simulés à l'aide d'un minuteur, fidèles à la véritable API JSON/WS) :

- [`app/`](app/) : le panneau de contrôle : parcourez les recettes et exécutez-les, avec une télémétrie en direct, des arrêts d'urgence (ANDON) et des restaurations. Conçu à partir de
[`design/ui-control-panel.claude-design-brief.md`](design/ui-control-panel.claude-design-brief.md)
(la carte complète des gestionnaires d’événements et les exigences en matière d’utilisabilité).

## Sécurité / modèle de menace

La **couche de recette** (`tensor-engine-knowledge/engines.db`) est l'entrée de connaissance fiable : les recettes vérifiées et documentées qui indiquent ce qui doit être construit et quels objectifs doivent être atteints. `engine-room` la traite comme la source de vérité.

`er provision --execute` est la seule commande qui affecte l'infrastructure. Elle est **protégée par un paramètre `--execute` et `--model` explicites** : toutes les autres commandes, et `provision` sans `--execute`, sont en lecture seule / exécution à sec. Lorsque vous exécutez la commande, elle :

- **télécharge** les artefacts fixes de la recette et **vérifie leur hachage SHA256** *lorsque le point fixe contient un hachage* ; les points fixes / hachages d'espace réservé sont actuellement acceptés (le problème n° 1 mentionné ci-dessus concernant le stockage, considérez la base de données des recettes et ses URL d'artefacts comme fiables jusqu'à ce que cette fonctionnalité soit implémentée),
- **extrait** les archives dans un répertoire spécifique à l'instance (jamais dans le PATH global),
- **lance** un serveur local (`127.0.0.1`) et peut **l'arrêter** ; la restauration est vérifiée par identité (elle ne tue qu'un PID dont l'exécutable se trouve dans notre répertoire d'instance, elle ne tue donc jamais un processus non lié).

Chaque étape irréversible est enregistrée dans un registre *avant* son exécution et possède un compensateur nommé, classé par ordre chronologique inverse (du plus récent au plus ancien). Pour signaler une vulnérabilité, consultez le fichier [`SECURITY.md`](SECURITY.md).

## Assistance

Le projet engine-room est **activement maintenu**. Les correctifs de sécurité sont intégrés dans la **dernière version mineure** (la branche 1.0.x) ; consultez le fichier [`SECURITY.md`](SECURITY.md) pour connaître les versions prises en charge et la procédure à suivre pour signaler une vulnérabilité en privé. Signalez les bogues et proposez de nouvelles fonctionnalités en créant des tickets sur GitHub.

## Licence

MIT — voir [LICENSE](LICENSE).

---

<p align="center">Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>.</p>
