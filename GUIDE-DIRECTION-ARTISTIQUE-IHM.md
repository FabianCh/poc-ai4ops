# Guide de direction artistique — IHM IA4Ops

Ce guide définit la direction visuelle de l’interface Chainlit d’IA4Ops. Il traduit les
principes de l’identité Wavestone en règles concrètes pour une interface de diagnostic
d’exploitation : lisible, sobre, professionnelle et orientée vers la décision de l’opérateur.

Il s’applique à l’application expérimentale [`ia4ops-agent-chat/`](ia4ops-agent-chat/), et à toute
future interface IA4Ops qui reprend son expérience de conversation.

## 1. Intention et principes

L’interface doit évoquer un assistant IA moderne intégré à un outil professionnel de diagnostic,
pas une page marketing ni un tableau de bord surchargé.

Priorités de conception :

1. **Clarté** : rendre visibles la demande, les observations, le diagnostic et ses limites.
2. **Confiance** : distinguer les données réellement collectées du contenu simulé ou généré.
3. **Maîtrise opérateur** : rendre explicite toute décision et ne jamais suggérer qu’une action a
   été exécutée si elle ne l’a pas été.
4. **Sobriété** : préférer l’espace, la typographie et des surfaces discrètes aux ornements.
5. **Accessibilité** : maintenir lisibilité, contraste et navigation clavier sur chaque parcours.

Une investigation reste en lecture seule. Une alerte reçue attend une décision humaine avant le
démarrage du diagnostic. Le style ne doit jamais masquer ni affaiblir ces garanties fonctionnelles.

## 2. Palette de couleurs

Utiliser uniquement les couleurs ci-dessous. Les couleurs fonctionnelles ne sont pas des couleurs
décoratives et doivent correspondre à une information réelle.

| Rôle | Couleur | Usage |
| --- | --- | --- |
| Fond principal | `#FFFFFF` | Fond de page et surfaces principales |
| Fond secondaire | `#F6F6F6` | Zones secondaires, cartes et éléments de conversation |
| Bleu Wavestone | `#451DC7` | Titres principaux, liens, action principale, sélection et focus |
| Bleu nuit | `#250F6B` | Navigation, sous-titres et surfaces sombres |
| Vert accent | `#04F06A` | Petit accent ou indicateur de succès, jamais CTA principal |
| Vert clair | `#CAFEE0` | Mise en évidence discrète d’une information positive |
| Attention / en cours | `#FFCA4A` | Alerte ou traitement en cours |
| Erreur / incident | `#FF2A49` | État d’erreur ou danger |
| Neutre / non démarré | `#CCCCCC` | État neutre lorsque nécessaire |
| Bleu infographique facultatif | `#4682B4` | Visualisation de données uniquement |
| Violet infographique facultatif | `#8F00FF` | Visualisation de données uniquement |

### Règles d’application

- Garder le fond blanc ou gris clair ; le texte courant est noir.
- Réserver le bleu Wavestone aux éléments de marque et aux interactions importantes. Le bleu nuit
  est un accent secondaire, pas une seconde couleur primaire concurrente.
- Le vert vif reste très minoritaire : ne pas l’utiliser pour du texte sur fond blanc, ni pour le
  texte d’un bouton. Ne jamais placer de texte blanc sur ce vert.
- Sur une surface bleu foncé, utiliser du texte blanc et vérifier le contraste de chaque élément.
- Ne pas inventer de couleurs de marque, multiplier les couleurs d’un graphique sans signification,
  utiliser des fonds beige/crème, ni ajouter des dégradés ou barres décoratives.
- Les couleurs d’état sont accompagnées d’un libellé ou d’une icône : la couleur seule ne porte
  jamais l’information.
- Vérifier le contraste réel des composants, notamment des petits textes, bordures, états
  désactivés et indicateurs, au lieu de supposer qu’une couleur de palette suffit.

## 3. Typographie et hiérarchie

- Utiliser **Aptos** lorsque la police est disponible ; prévoir une police sans sérif de repli.
- Titre de page : Aptos SemiBold, bleu `#451DC7`.
- Titres de section : Aptos Medium ou SemiBold, bleu `#451DC7` ou bleu nuit `#250F6B`.
- Texte courant : Aptos, noir.
- Texte secondaire : Aptos, gris neutre suffisamment contrasté.
- Limiter le nombre de tailles et de graisses. Structurer plutôt avec des titres explicites, des
  espacements réguliers et des listes courtes.
- Dans les réponses longues, utiliser des titres Markdown, des paragraphes brefs, des listes et des
  références clairement séparées.

## 4. Composition et surfaces

- Construire chaque écran autour d’un objectif principal et d’une hiérarchie immédiatement lisible.
- Aligner les éléments sur une grille cohérente et conserver des marges généreuses.
- Séparer les sections par l’espace, la typographie et de subtils changements de fond avant
  d’ajouter des bordures.
- Employer des cartes blanches ou gris clair, avec un padding confortable, des coins modérément
  arrondis et une bordure ou ombre discrète uniquement si cela améliore la lecture.
- Utiliser `#CAFEE0` avec parcimonie pour mettre en évidence une information positive ou utile.
- Éviter les panneaux denses, les cadres répétés, les cartes décoratives et les séparateurs lourds.
- L’interface reste un outil de travail : le logo Wavestone, s’il est utilisé, reste discret. Choisir
  la variante couleur sur fond clair et la variante blanche sur fond bleu foncé.

## 5. Parcours de conversation IA4Ops

### Messages

- Distinguer visuellement les messages opérateur et assistant de façon subtile et cohérente.
- Garder des bulles contenues et une largeur de lecture confortable ; ne pas transformer le chat en
  colonnes de cartes imbriquées.
- Prioriser la lisibilité des rapports : observations collectées, limites, diagnostic, preuves et
  prochaines vérifications doivent rester repérables dans cet ordre logique.
- Présenter les références et valeurs techniques avec une mise en forme compacte et lisible.

### Investigation manuelle

- Expliquer clairement le format de commande `/investigate <service> [minutes] | <question>` et
  les bornes applicables, sans surcharger l’écran.
- Garder la zone de saisie visible et simple ; l’action d’envoi utilise le bleu Wavestone.
- Ne pas faire croire qu’un diagnostic est terminé pendant l’attente ; afficher un état de traitement
  explicite et non ambigu.

### Alertes et décisions opérateur

- Présenter chaque alerte comme une décision à prendre, en affichant les informations essentielles :
  nom, service, namespace, sévérité, début et résumé lorsqu’ils sont disponibles.
- Donner un poids visuel équivalent et compréhensible aux actions **Investiguer** et **Ignorer** ;
  l’action principale peut utiliser le bleu et l’action secondaire un fond clair.
- Ne pas utiliser le rouge pour dramatiser une alerte normale : réserver les couleurs fonctionnelles
  à leur sens réel.
- Rendre explicite qu’aucune collecte ni aucun diagnostic ne démarre à la réception du webhook seul.
- Si la décision a déjà été prise ou si l’alerte est résolue, expliquer l’état plutôt que laisser des
  actions périmées paraître encore disponibles.

### Résultats, données simulées et erreurs

- Séparer visuellement les **observations collectées** du **diagnostic généré** et de ses preuves.
- Lorsqu’un provider ou le LLM fonctionne en mode mock, afficher un avertissement textuel visible
  près du contenu concerné. Ne pas laisser croire que des données synthétiques sont issues de
  Grafana ou que le diagnostic est déduit des observations réelles.
- Afficher les données manquantes, limites et erreurs avec un libellé explicite et une couleur
  fonctionnelle appropriée ; ne jamais présenter un échec comme une réussite.
- Pour toute suggestion de remédiation, rappeler qu’elle est proposée et non exécutée. L’interface
  actuelle est en lecture seule.

### Suggestions et actions de démarrage

- Présenter les actions de démarrage sous forme de cartes sobres, pastilles ou boutons secondaires.
- Limiter le nombre d’actions mises en avant et employer les couleurs bleues de la palette.
- Éviter de concurrencer l’action d’investigation principale avec des appels à l’action décoratifs.

## 6. Boutons, liens et états interactifs

- Action principale : fond `#451DC7`, texte blanc.
- Action secondaire : fond blanc ou `#F6F6F6`, texte et bordure `#451DC7`.
- Action dangereuse : `#FF2A49` uniquement si l’action est effectivement destructive ou risquée.
- Succès : vert utilisé avec parcimonie, accompagné d’un libellé lisible.
- Donner aux éléments interactifs des libellés explicites, des états désactivés compréhensibles et
  des états de survol/focus visibles.
- Le focus clavier doit être clairement visible et cohérent avec le bleu de marque.
- Ne pas utiliser un lien sans préciser sa destination ou son intention.

## 7. Icônes, logo et images

- Préférer des icônes simples, cohérentes et de style linéaire.
- Employer le bleu Wavestone ou le bleu nuit sur fond clair, et le blanc sur fond bleu foncé.
- Utiliser les ressources officielles Wavestone lorsqu’elles sont disponibles ; ne pas créer de
  substitut ressemblant à un logo officiel.
- Une image informative possède un texte alternatif pertinent ; une image purement décorative est
  ignorée par les technologies d’assistance.
- L’imagerie n’est pas nécessaire à l’expérience de diagnostic. Si elle est ajoutée, privilégier des
  compositions authentiques, modernes et professionnelles, sans photographie générique de stock.

## 8. Accessibilité

- Concevoir tous les parcours pour une utilisation au clavier, y compris la saisie, les liens, les
  actions sur alerte et les contrôles du chat.
- Maintenir un contraste suffisant pour le texte et les composants, ainsi qu’une taille de texte
  confortable.
- Ne jamais communiquer une sévérité, une décision ou un état uniquement par la couleur ou une icône.
- Ajouter un texte alternatif aux images significatives ; ignorer les éléments décoratifs.
- Employer des libellés explicites pour les liens et les contrôles.
- Développer les abréviations lors de leur première apparition (par exemple, « p95 » si le contexte
  n’est pas déjà clair pour l’audience).
- Conserver les titres dans un ordre logique et la structure Markdown sémantique dans les rapports.

## 9. Mise en œuvre dans Chainlit

- Traduire ces règles via les mécanismes Chainlit pris en charge (configuration UI, thème, CSS
  personnalisé et ressources publiques) ; limiter les personnalisations qui fragilisent les mises
  à jour du frontend.
- Garder la configuration et les ressources visuelles propres à `ia4ops-agent-chat` : cette copie
  expérimentale est isolée de l’agent stable.
- Ne pas activer de HTML non sûr ou de script client simplement pour obtenir un effet visuel.
- Valider le rendu en navigateur, en clair et sombre si ces thèmes sont proposés, et à plusieurs
  tailles d’écran ; vérifier clavier, focus, lisibilité des messages longs, alertes et avertissements
  de mode mock.
- Une identité visuelle soignée ne remplace pas le contrôle d’accès : tant que l’authentification
  n’est pas intégrée et vérifiée, l’IHM ne doit pas être exposée publiquement.

## 10. Contrôle rapide avant livraison

- [ ] L’écran a un objectif principal et une hiérarchie claire.
- [ ] Les couleurs sont limitées à la palette et ont un rôle explicite.
- [ ] Les actions principales sont bleues ; le vert n’est ni une couleur de CTA ni du texte sur blanc.
- [ ] Les observations réelles, données mockées, diagnostic, limites et actions non exécutées sont
      clairement différenciés.
- [ ] Une alerte ne déclenche pas visuellement ou fonctionnellement un diagnostic sans décision
      humaine.
- [ ] Les états et actions sont compréhensibles sans perception des couleurs.
- [ ] Les parcours sont utilisables au clavier et les focus sont visibles.
- [ ] Les textes restent lisibles dans une réponse longue et sur une fenêtre étroite.
- [ ] Aucun élément visuel ne laisse croire à une authentification, une remédiation ou une
      validation qui n’existe pas.

**Règle finale :** en cas d’hésitation, choisir le plus simple. Clarté avant décoration, espace avant
densité, hiérarchie avant effets visuels, bleu Wavestone avant toute couleur supplémentaire.
