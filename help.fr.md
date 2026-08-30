# Hello World — l'exemple de référence

Ce plugin **n'a aucun usage en production**. Il incruste « Hello World », un logo et les
informations système sur l'image. Sa raison d'être est ailleurs : c'est la **référence
exécutable** du contrat de plugin, celle qu'on lit avant d'en écrire un.

> Le code du plugin est commenté **en anglais** : il vit dans un dépôt public destiné à être lu
> au-delà de l'équipe. Cette page-ci, elle, suit la langue de l'interface.

## À quoi il sert vraiment

**Vérifier une installation neuve.** Déployez-le sans rien câbler : il génère son propre fond et
affiche le nom du conteneur, sa version, les flux de sortie, le format, la cadence et la durée de
marche. Si l'image apparaît dans le monitoring, c'est que la chaîne complète fonctionne —
orchestrateur, agent, bus MXL, métriques.

**Apprendre le contrat.** Son `script.py` est commenté pour être lu : chaque règle y est
accompagnée du *pourquoi* et de ce qui casse **en silence** si on l'ignore.

## Ce qu'il démontre

| Point du contrat | Où le voir |
|---|---|
| Gabarit `str.format`, accolades doublées | en-tête du script |
| Mode tranche natif et commit progressif | `slice_height_pour()` et la boucle principale |
| Traitement **ligne-local** et offset absolu | `incruster()` — le piège numéro un du mode tranche |
| Cache par signature | `overlay_pour()` — première cause de déficit de cadence quand il manque |
| Trois essences en entrée comme en sortie | lecteurs/écrivains vidéo, audio et ANC, hook `wire_followers` |
| ANC écrit en RFC 8331 | `anc_pack_rfc8331` — un format maison se décode « à zéro paquet », en silence |
| Exposition aux macros | `param_tree` et `actions` du manifeste, endpoints `/params` et `/dispo` |
| État lisible en condition | `/state`, déclaré dans `control.read_endpoints` |
| Métriques d'observabilité | `slice_mode`, `own_latency_ms`, `source`, `slices_incompletes` — pas seulement `fps` |
| Reprise sur SIGBUS et flux recréé | gestionnaire `_sigbus` et boucle de reprise |
| Page publique | `ui.public_page`, la console honore `ctx.base` |

## Réglages

| Réglage | Effet |
|---|---|
| Texte incrusté | La ligne affichée en gros. Les accents sont translittérés — la police intégrée n'a pas leurs glyphes. |
| Disposition | Le PiP, les vu-mètres et le cartouche se placent et se dimensionnent dans l'éditeur, sur la page du plugin. Rectangles normalisés, donc une disposition survit à un changement de format. L'action `dispo_defaut` rappelle le défaut. |
| Couleur de fond | Liste vivante servie par `/couleurs`, qui alimente aussi l'éditeur de macros. |
| Incrustation / PiP | Actions d'affichage et de masquage, déclenchables par macro. |
| Format de sortie | Choisi parmi les formats nommés du site, **uniquement** sans entrée vidéo câblée. Avec une source, le format vient du flux. Le changer REDÉPLOIE le plugin. |
| Colonne de libellé / niveau de tally | Lus par l'orchestrateur, pas par le conteneur : ils ne prennent effet qu'au redéploiement. |

## Le PiP et le mode tranche

Un PiP qui touche le **bord bas** est servi depuis la trame en cours. Ailleurs, il réclame des
lignes d'entrée pas encore arrivées — il est donc servi depuis la trame **précédente**, et la
sortie reste tranchée. Le coût porte alors sur la seule vignette (une trame de retard, comptée par
`pip_retard_trames`) au lieu de tout le signal. L'éditeur dit lequel des deux s'applique, avant
qu'on le paie.

## Garde-fou

`tools/verif_plugin_hello_world.py` vérifie en intégration continue que cet exemple honore
toujours les points ci-dessus. Si le contrat évolue sans que l'exemple suive, **la CI échoue** —
c'est ce qui l'empêche de devenir une documentation périmée que plus personne n'exécute.

## Cette page est produite par le plugin lui-même

Le fichier `help.md` posé à la racine du plugin **est** cet article. `/api/plugins/help` agrège
les `help.md` de tous les plugins installés, les rend en HTML et la page Aide en fabrique un
article `plugin-<type>`. Il n'y a rien à déclarer et rien à recopier ailleurs.

Un plugin peut poser un `help.<code>.md` à côté (`help.fr.md`, `help.en.md`) : c'est celui de la
langue courante qui est servi, avec repli sur `help.md`. Quand le repli joue, l'article le DIT —
sinon une aide dans une autre langue se lit comme un défaut de traduction du produit.

Deux détails qui se paient si on les ignore :

- le titre `# …` de tête est **retiré** au rendu — l'article porte déjà le libellé du plugin, et
  le garder produirait deux titres de niveau 1 ;
- le rangement vient de `help.category` et `help.order` du manifeste, avec repli sur la section
  de `nav`. Sans `help`, un plugin d'exemple atterrit au milieu des Traitements, là où
  l'exploitant cherche des outils de production.
