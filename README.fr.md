![Liquid Memory — SAWM et Basira](assets/hero.svg)

# Liquid Memory · La mémoire des agents qui durent

**Un agent peut changer de sujet. Son histoire doit rester disponible.**

[English](README.md) · [Guide développeur](docs/agents-and-characters.md) · [Documentation Basira](https://basira.sawm.io/documentation)

Ce dépôt montre comment connecter votre modèle, votre assistant, un employé
numérique ou un personnage à **Basira, TSST et ODVL dans le Cloud**. Le but :
conserver les informations utiles, suivre leurs changements et reprendre une
mission ou un ancien sujet avec des preuves.

La mémoire apporte aussi une continuité aux personnages : votre modèle peut
s'appuyer sur leurs expériences pour faire évoluer **leur caractère, leurs
humeurs et les sentiments qu'ils expriment**. Ces états sont des interprétations
produites par le modèle et mémorisées avec leurs sources ; ODVL ne constitue
pas à lui seul un générateur d'émotions.

## Des mondes qui restent distincts

Une mission, un jeu, un dossier client, le profil d'un personnage : chacun peut
avoir son monde. Ici, chaque monde correspond à une entité Basira. Votre modèle
ou votre application choisit son identifiant ; les recherches utilisent cette
portée explicite.

Exemple : la tasse est d'abord dans la cuisine. L'agent passe à une mission de
travail, puis revient à la maison et enregistre la tasse sur l'étagère. Il peut
retrouver **l'état courant et la trace des anciennes déclarations**, sans
remplacer son dossier professionnel par les objets du jeu.

![Changer de monde et reprendre une tâche avec son historique](assets/continuity.svg)

## Essayer sans clé

```sh
git clone https://github.com/SAWM-io/liquid-memory.git
cd liquid-memory
python demo.py
python -m unittest discover -s tests -v
```

Cette démonstration hors ligne utilise des données fictives et un faux transport
pour tester l'intégration. Elle ne simule pas les moteurs propriétaires et ne
mesure pas leurs performances.

## Brancher Basira Cloud

```sh
python -m pip install -r requirements.txt
python bootstrap_sdk.py
```

Le SDK officiel est téléchargé depuis Basira et vérifié par SHA-256. Définissez
`BASIRA_SPACE` et `BASIRA_KEY` dans votre environnement, puis :

```sh
python demo.py --cloud --state .state/memory.json
```

Ce mode écrit des faits fictifs dans votre espace et utilise son quota. Les
permissions et la configuration Windows sont détaillées dans le
[README principal](README.md#connect-the-real-cloud). La démonstration ne déclenche aucune suppression. Une procédure de purge
explicite est documentée séparément. Ne publiez jamais vos clés ni votre répertoire `.state/`.

## Dans votre code

```python
from memory import WorldMemory

# cloud : instance du SDK officiel BasiraClient, configurée côté serveur.
memory = WorldMemory(cloud, ".state/agent.json", space_id)
memory.create_world("agent-1/projet-orion")

# Appeler après confirmation du système qui exécute l'action.
memory.record_fact(
    "agent-1/projet-orion", "livraison.date",
    "La livraison est confirmée pour vendredi.",
    "Confirmation du planning, référence exemple-42.",
    operation_id="planning-42", epistemic_status="observed",
)
preuves = memory.recall("agent-1/projet-orion", "Quand a lieu la livraison ?")
```

Le modèle peut lire ces preuves avant de répondre. Pour modifier une information,
il conserve sa clé de fait et utilise un nouvel identifiant d'opération. En cas
d'interruption, il rejoue la même opération avec le même contenu. La confirmation
n'intervient qu'après réception de l'accusé Cloud attendu.

Pour une équipe : mondes et droits propres à chaque agent, et un coordinateur
unique pour les écritures d'une mission partagée. Le [guide développeur](docs/agents-and-characters.md)
explique aussi comment relier les expériences aux états de caractère et aux
humeurs, avec des sources et un historique.

## Flashback, traçabilité et effacement

| Fonction | Utilisation pour votre agent ou chatbot |
| --- | --- |
| Flashback | Consulter les preuves à une date de validité ou de connaissance passée. |
| Révisions | Corriger un fait en gardant la trace des versions confirmées. |
| Provenance | Relier les informations aux sources, dates, identifiants et reçus Cloud. |
| Export de trace | `memory.trace(monde)` produit un JSON limité à cet index local. |
| Purge ciblée | `purge_world()` bloque la réutilisation et exige la confirmation de la mémoire et d’ODVL. |
| Droits multi-agents | Séparer les périmètres par espaces, entités, clés et grants. |

Le [guide avec exemples de code](docs/governance.md) explique ces mécanismes et
leurs limites. **Ils contribuent à votre démarche de conformité ; ils ne sont
pas une certification ni une conformité automatique au RGPD, à l’AI Act ou à
NIS2.** Le périmètre, les finalités, la rétention, les sauvegardes et les droits
des personnes restent à traiter au niveau de votre application.

La trace locale n’est pas un export exhaustif de l’audit Cloud. Après une purge,
prenez aussi en charge les copies, exports et sauvegardes de votre application.
Aucune purge réelle n’a été exécutée pour tester ce dépôt.

## Une base pour le très long terme

La mémoire persistante peut accompagner une mission sur plusieurs sessions,
jours ou davantage, sous réserve de maintenir le service, les données et leurs
sauvegardes. **La durée de conservation et la fiabilité du rappel sont deux
choses différentes.** Ce dépôt ne promet pas un rappel parfait ou une autonomie
sur plusieurs années déjà démontrée.

L'index local garde les reçus et les sources connus de cet agent : `resume()`
le relit. Il doit être sauvegardé ; ce n'est pas une restauration automatique
de tout le Cloud. Les recherches TSST sont limitées à dix résultats par appel,
pas à dix souvenirs stockés. L'absence d'un résultat ne prouve pas l'absence
d'un souvenir. Le modèle, la détection automatique des sujets et les validations
métier sont à connecter par votre application.

[Licence MIT](LICENSE) pour cet exemple et ses visuels. Les moteurs Cloud ne sont
pas publiés dans ce dépôt. [Périmètre](NOTICE.md).
