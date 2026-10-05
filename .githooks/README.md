# Git Hooks

Les hooks de ce dépôt sont versionnés dans `.githooks/`.

## Activation (à faire une seule fois après le clone)

```bash
git config core.hooksPath .githooks
```

## Hooks disponibles

### `pre-commit` — Protection secrets

Bloque un commit si les fichiers suivants sont staged :
- Fichiers `.env` (sauf `.env.example`)
- Fichiers de credentials JSON GCP (`service-account*.json`, `credentials*.json`, etc.)
- Contenu contenant une clé privée PEM (`BEGIN PRIVATE KEY`)

En cas de blocage :
```bash
git reset HEAD <fichier-sensible>
git commit ...   # réessayer sans le fichier problématique
```
