#!/usr/bin/env bash
# Crée (hors Git) les Secrets de Keep et la clé d'API utilisée par Alertmanager.
# Le dépôt est public : aucun secret n'y est versionné, ils sont générés ici, une fois.
#
#   keep/keep-backend-auth        KEEP_JWT_SECRET, KEEP_DEFAULT_PASSWORD, KEEP_DEFAULT_API_KEYS
#   keep/keep-frontend-auth       NEXTAUTH_SECRET
#   monitoring/keep-alertmanager-api-key   api-key (clé d'API de rôle "webhook", lue par Alertmanager)
#
# Idempotent : si keep-backend-auth existe déjà, rien n'est régénéré (le mot de passe admin
# et la clé d'API sont figés dans la base de Keep au premier démarrage) ; seul le Secret
# d'Alertmanager est recréé à partir de la clé existante.
#
# Usage : make create-keep-secrets   (kubectl doit joindre le cluster : make kubeconfig / make tunnel)
set -euo pipefail

KEEP_NS=keep
MON_NS=monitoring
API_KEY_NAME=alertmanager

ensure_namespace() {
  kubectl create namespace "$1" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
}

# Les valeurs passent par stdin (jamais en argument de commande, visible dans ps).
apply_secret() { # <namespace> <name> puis lignes "clé: valeur" sur stdin
  local ns="$1" name="$2"
  {
    printf 'apiVersion: v1\nkind: Secret\nmetadata:\n  name: %s\n  namespace: %s\ntype: Opaque\nstringData:\n' "$name" "$ns"
    sed 's/^/  /'
  } | kubectl apply -f - >/dev/null
}

ensure_namespace "$KEEP_NS"
ensure_namespace "$MON_NS"

if existing="$(kubectl -n "$KEEP_NS" get secret keep-backend-auth -o jsonpath='{.data.KEEP_DEFAULT_API_KEYS}' 2>/dev/null)" && [[ -n "$existing" ]]; then
  # format "nom:rôle:secret" : la clé est le dernier champ
  api_key="$(printf '%s' "$existing" | base64 -d | awk -F: '{print $NF}')"
  created=false
else
  api_key="$(openssl rand -hex 32)"
  password="$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | cut -c1-20)"
  apply_secret "$KEEP_NS" keep-backend-auth <<SECRET
KEEP_JWT_SECRET: "$(openssl rand -hex 32)"
KEEP_DEFAULT_PASSWORD: "$password"
KEEP_DEFAULT_API_KEYS: "$API_KEY_NAME:webhook:$api_key"
SECRET
  apply_secret "$KEEP_NS" keep-frontend-auth <<SECRET
NEXTAUTH_SECRET: "$(openssl rand -hex 32)"
SECRET
  created=true
fi

apply_secret "$MON_NS" keep-alertmanager-api-key <<SECRET
api-key: "$api_key"
SECRET

if [[ "$created" == true ]]; then
  echo "Secrets créés. Connexion à Keep : utilisateur 'admin', mot de passe : $password" >&2
  echo "(à noter maintenant ; relisible ensuite avec la commande de docs/cloudshell.md)" >&2
else
  echo "Secrets de Keep déjà présents : conservés. Secret Alertmanager resynchronisé." >&2
fi
