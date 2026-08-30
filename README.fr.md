# Hello World — l'exemple de référence d'un plugin Bobi.Studio

*[English version](README.md)*

Ce plugin **n'a aucun usage en production**. Il incruste « Hello World », un logo et les
informations système sur l'image. Sa raison d'être est ailleurs : c'est la **référence
exécutable** du contrat de plugin — celle qu'on lit avant d'en écrire un, et celle que
l'intégration continue vérifie pour que la documentation ne puisse pas se périmer en silence.

Il fait partie de [Bobi.Studio](https://github.com/bob-integration/bobistudio), un
orchestrateur broadcast bâti sur le bus ST 2110 / MXL.

---

## À quoi il sert vraiment

**Vérifier une installation neuve.** Déployez-le sans rien câbler : il génère son propre fond et
affiche le nom du conteneur, sa version, les flux de sortie, le format, la cadence et la durée
de marche. Si l'image arrive dans le monitoring, c'est que la chaîne complète fonctionne —
orchestrateur, agent, bus MXL, métriques. C'est le jour de l'installation que ça compte le plus,
et c'est justement le jour où aucune chaîne n'est encore montée.

**Apprendre le contrat.** `script.py` est commenté pour être lu. Chaque règle porte le
*pourquoi* et, surtout, **ce qui casse en silence** si on l'omet — parce que dans ce produit
presque rien ne tombe bruyamment. Un étage qui n'émet plus rien tourne encore, répond encore sur
ses deux ports, et affiche encore une cadence parfaite.

---

## Ce qu'il démontre

| Point du contrat | Où regarder |
|---|---|
| Gabarit `str.format`, accolades doublées | en-tête du script |
| Mode tranche natif, commit progressif | `slice_height_pour()` et la boucle principale |
| Traitement **ligne-local**, offset absolu | `incruster()` — le piège numéro un du mode tranche |
| Cache par signature, et comment savoir qu'il sert | `overlay_pour()`, métrique `overlay_rendus_par_s` |
| Trois essences en entrée comme en sortie | lecteurs/écrivains vidéo, audio, ANC, hook `wire_followers` |
| ANC écrit en RFC 8331 | un format maison se décode « à zéro paquet », en silence |
| Exposition aux macros | `param_tree`, `actions`, listes d'options vivantes |
| État lisible en condition d'automatisme | `/state`, déclaré dans `control.read_endpoints` |
| Métriques d'observabilité | `slice_mode`, `own_latency_ms`, `slices_incompletes`, … |
| Reprise sur SIGBUS et flux recréé | `_sigbus` et la boucle de reprise |
| Page publique en lecture seule | `ui.public_page`, la console honore `ctx.base` |

Il lit de la vidéo, de l'audio et de l'ANC, et republie les trois — le cas de câblage où les
erreurs coûtent le plus cher (audio muet, ANC perdu, une entrée prise pour une autre).

---

## L'installer

**Depuis Bobi.Studio** — Réglages → Plugins → *Importer*, avec un paquet `.mxlplugin`, ou la
page **Catalogue**, qui liste les paquets publiés et les installe pour vous.

**À la main** — clonez ce dépôt dans `plugins/hello_world/` d'une instance Bobi.Studio, puis
rechargez le registre des plugins (Réglages → Plugins → *Recharger*).

> Ajouter ou modifier `hooks.py` **exige un rechargement du registre** : l'orchestrateur
> l'importe une fois, au scan. Un hook qui ne se déclenche jamais est une panne parfaitement
> silencieuse — ce plugin publie `tally_age_s` précisément pour que sa propre absence se voie.

---

## Le lire

Commencez par l'en-tête de `script.py` : il énumère les sept points du contrat et les pièges.
Suivez ensuite la boucle principale — c'est la forme qu'a tout plugin.

- `script.py` — le plugin entier, un gabarit `str.format` rendu par l'orchestrateur et exécuté
  dans le conteneur. **Toute accolade littérale doit être doublée `{{ }}`**, commentaires
  compris.
- `hooks.py` — les hooks de cycle de vie. Ce fichier tourne **dans l'orchestrateur**, et c'est
  l'unique exception documentée à la règle « aucun code de plugin dans le contrôleur ».
- `control.js` / `control.css` / `control.html` — la console. Les contrôles viennent du
  catalogue partagé (`window.MXLControls`), l'éditeur de disposition du moteur partagé
  (`window.MXLLayout`) ; ni l'un ni l'autre n'est réécrit ici.
- `plugin.json` — le manifeste : câblage, schéma de configuration, surface de macros, endpoints
  de contrôle.
- `help.md` / `help.fr.md` — l'article que la page Aide du produit fabrique depuis ce plugin.

---

## Comportement mesuré

En 1080p50, sur un nœud, les trois entrées câblées :

| | |
|---|---|
| Cadence | 50,0 i/s |
| Calcul par trame | 18,8 ms, sur un budget de 20 |
| Trames tronquées | 0 |
| Rendus du cartouche | 8 /s (borné — sinon la clé de cache changerait à chaque trame) |

Ces chiffres ne sont pas décoratifs. Le plugin les publie pour qu'un choix de placement —
décoller le PiP du bord bas, élargir le cartouche — montre son coût au lieu de le cacher.

---

## Le garde-fou

`tools/verif_plugin_hello_world.py` — qui vit dans le
[dépôt Bobi.Studio](https://github.com/bob-integration/bobistudio), pas ici — passe 30 contrôles
sur ce plugin en intégration continue : le gabarit se rend *et compile*, le mode tranche est
actif, les macros sont atteignables, les métriques sont déclarées *et* mises à jour, les trois
essences sont câblées dans les deux sens, SIGBUS est intercepté, le contrat de page publique est
honoré.

Si le contrat évolue sans que cet exemple suive, **la CI échoue**. C'est ce qui l'empêche de
devenir une documentation que plus personne n'exécute — `plugins/AUTHORING.md` a passé trois
mois à décrire un contrat qui avait changé sous lui.

---

## Licence

GPL-3.0-or-later — voir [LICENSE](LICENSE). Copyright © 2026 BOBI SAS, France.
