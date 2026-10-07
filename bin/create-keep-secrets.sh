#!/usr/bin/env bash
# Crée (hors Git) les Secrets de Keep et les clés d'API de ses clients.
# Le dépôt est public : aucun secret n'y est versionné, ils sont générés ici, une fois.
#
#   keep/keep-backend-auth        KEEP_JWT_SECRET, KEEP_DEFAULT_PASSWORD, KEEP_DEFAULT_API_KEYS
#                                 (liste "nom:rôle:secret" : alertmanager:webhook, ia4ops-agent:admin)
#   keep/keep-frontend-auth       NEXTAUTH_SECRET
#   monitoring/keep-alertmanager-api-key   api-key (rôle webhook, lue par Alertmanager)
#   ia4ops/ia4ops-agent-keep      KEEP_API_KEY (rôle admin, lue par l'agent IA4Ops)
#
# Idempotent : rien n'est régénéré si les Secrets existent déjà (le mot de passe admin et les
# clés sont figés dans la base de Keep au premier démarrage). Une clé manquante est ajoutée à
# KEEP_DEFAULT_API_KEYS sans toucher aux autres, puis keep-backend est redémarré : Keep ne
# provisionne ses clés qu'au démarrage. Aucune clé n'est affichée.
#
# Usage : make create-keep-secrets   (kubectl doit joindre le cluster : make kubeconfig / make tunnel)
set -euo pipefail

KEEP_NS=keep
MON_NS=monitoring
AGENT_NS=ia4ops
AM_KEY_NAME=alertmanager
AGENT_KEY_NAME=ia4ops-agent
AGENT_KEY_ROLE="admin" # seul rôle Keep cumulant read:alert et write:incident (pas de rôle sur mesure)

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

# entry_secret <liste "nom:rôle:secret,..."> <nom> : secret de l'entrée, vide si absente
entry_secret() {
  printf '%s' "$1" | tr ',' '\n' | awk -F: -v n="$2" '$1 == n {print $3}'
}

ensure_namespace "$KEEP_NS"
ensure_namespace "$MON_NS"
ensure_namespace "$AGENT_NS"

created=false
restart=false

if entries="$(kubectl -n "$KEEP_NS" get secret keep-backend-auth -o jsonpath='{.data.KEEP_DEFAULT_API_KEYS}' 2>/dev/null | base64 -d)" && [[ -n "$entries" ]]; then
  am_key="$(entry_secret "$entries" "$AM_KEY_NAME")"
  if [[ -z "$am_key" ]]; then
    echo "Clé '$AM_KEY_NAME' introuvable dans keep-backend-auth : état inattendu, abandon." >&2
    exit 1
  fi
  agent_key="$(entry_secret "$entries" "$AGENT_KEY_NAME")"
  if [[ -z "$agent_key" ]]; then
    # Ajoute la clé de l'agent à la liste, sans modifier ni remplacer les clés existantes.
    agent_key="$(openssl rand -hex 32)"
    new_entries="$entries,$AGENT_KEY_NAME:$AGENT_KEY_ROLE:$agent_key"
    printf '{"data":{"KEEP_DEFAULT_API_KEYS":"%s"}}' "$(printf '%s' "$new_entries" | base64 -w0)" \
      | kubectl -n "$KEEP_NS" patch secret keep-backend-auth --type merge --patch-file=/dev/stdin >/dev/null
    restart=true
  fi
else
  am_key="$(openssl rand -hex 32)"
  agent_key="$(openssl rand -hex 32)"
  password="$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | cut -c1-20)"
  apply_secret "$KEEP_NS" keep-backend-auth <<SECRET
KEEP_JWT_SECRET: "$(openssl rand -hex 32)"
KEEP_DEFAULT_PASSWORD: "$password"
KEEP_DEFAULT_API_KEYS: "$AM_KEY_NAME:webhook:$am_key,$AGENT_KEY_NAME:$AGENT_KEY_ROLE:$agent_key"
SECRET
  apply_secret "$KEEP_NS" keep-frontend-auth <<SECRET
NEXTAUTH_SECRET: "$(openssl rand -hex 32)"
SECRET
  created=true
fi

apply_secret "$MON_NS" keep-alertmanager-api-key <<SECRET
api-key: "$am_key"
SECRET
agent_secret_new=false
kubectl -n "$AGENT_NS" get secret ia4ops-agent-keep >/dev/null 2>&1 || agent_secret_new=true
apply_secret "$AGENT_NS" ia4ops-agent-keep <<SECRET
KEEP_API_KEY: "$agent_key"
SECRET

# L'agent lit KEEP_API_KEY au démarrage (variable d'environnement) : redémarrage si le Secret vient d'apparaître.
if [[ "$agent_secret_new" == true ]] && kubectl -n "$AGENT_NS" get deployment ia4ops-agent >/dev/null 2>&1; then
  kubectl -n "$AGENT_NS" rollout restart deployment/ia4ops-agent >/dev/null
fi

if [[ "$restart" == true ]]; then
  # Keep ne lit KEEP_DEFAULT_API_KEYS qu'au démarrage du backend.
  if kubectl -n "$KEEP_NS" get deployment keep-backend >/dev/null 2>&1; then
    kubectl -n "$KEEP_NS" rollout restart deployment/keep-backend >/dev/null
    kubectl -n "$KEEP_NS" rollout status deployment/keep-backend --timeout=300s >&2
  fi
  echo "Clé '$AGENT_KEY_NAME' ajoutée (rôle $AGENT_KEY_ROLE), clé '$AM_KEY_NAME' inchangée. keep-backend redémarré." >&2
elif [[ "$created" == true ]]; then
  echo "Secrets créés. Connexion à Keep : utilisateur 'admin', mot de passe : $password" >&2
  echo "(à noter maintenant ; relisible ensuite avec make get-keep-password)" >&2
else
  echo "Secrets de Keep déjà présents : conservés. Secrets Alertmanager et agent resynchronisés." >&2
fi
