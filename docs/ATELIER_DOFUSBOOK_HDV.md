# Atelier Dofusbook + banque / inventaire

Module **lecture seule** ajouté à l'onglet **Atelier** de chaque compte connecté.

## Utilisation

1. Démarrer le bot, sélectionner le personnage, ouvrir **Atelier**.
2. Ouvrir sa banque en jeu au moins une fois : l'état `bank_content_known`
   est renseigné seulement quand le serveur envoie un contenu complet.
3. Rechercher des objets craftables dans le champ **Recette**, choisir la
   quantité et ajouter tous les éléments du stuff. Le calculateur additionne
   leurs ingrédients, puis affiche pour chaque ressource les quantités dans
   la banque, dans l'inventaire et ce qu'il manque.
4. **Autre option** : importer une liste de ressources Dofusbook. Coller le
   lien HTTPS d'un atelier **public** Dofusbook et cliquer **Lire le lien**.
   Si le site impose une connexion ou ne renvoie pas la liste dans son HTML,
   ouvrir l'atelier dans le navigateur, copier la liste visible des ressources
   et quantités puis la coller dans le champ texte. Formats reconnus :
   `Ressource` suivi de `0 / 12`, `Ressource x 12`, `12 x Ressource`.
5. Cliquer **Copier la liste des ressources manquantes** pour obtenir une liste
   de courses.

### Notes

- Les données de recettes sont celles du catalogue local d'AstraBot
  (`display_catalog.json`), et non celles d'une API Dofusbook.
- Aucune API Dofusbook d'accès authentifié n'est utilisée : pas de cookie,
  mot de passe, token, ni modification de l'atelier sur leur site.
- Importer un atelier remplace les crafts locaux ; ajouter ensuite un craft
  local remplace la liste importée, après confirmation.
- Si la banque ou l'inventaire n'ont pas été reçus, la colonne **Manquant**
  indique **À confirmer** au lieu d'inventer des quantités.
- Un scan de banque est une observation passive du contenu reçu lors de
  l'ouverture en jeu : le module ne déclenche ni trajet, ni retrait, ni vente.
- La lecture d'un lien public est asynchrone et limitée aux hôtes Dofusbook.
  L'import HTML est **best effort**, dépendant des pages publiques publiées
  par le site ; le collage est la méthode de secours fiable.
- La liste de crafts de l'interface n'est pas encore persistée après
  fermeture de l'application.

### Tests ciblés

```powershell
uv run pytest tests/test_craft_material_planner.py
uv run python __main__.py
```
