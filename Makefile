SHELL := /usr/bin/env bash
TF_DIR := infra/gcp-k3s
TF := terraform -chdir=$(TF_DIR)
export KUBECONFIG ?= $(CURDIR)/.kube/config

.DEFAULT_GOAL := help

.PHONY: help
help: ## Affiche cette aide
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

## --- Infrastructure (GCP + k3s) ---
.PHONY: init plan apply destroy output
init: ## terraform init
	$(TF) init

plan: ## terraform plan
	$(TF) plan

apply: ## Crée la VM k3s sur GCP
	$(TF) apply

destroy: ## Détruit toute l'infrastructure
	$(TF) destroy

output: ## Affiche les outputs Terraform
	$(TF) output

## --- Accès au cluster ---
.PHONY: ssh logs kubeconfig kubeconfig-iap tunnel
ssh: ## SSH sur la VM (via IAP)
	eval "$$($(TF) output -raw ssh_command)"

logs: ## Suit les logs du bootstrap k3s
	eval "$$($(TF) output -raw bootstrap_logs_command)"

kubeconfig: ## Récupère le kubeconfig (API sur l'IP publique)
	bin/get-kubeconfig.sh

kubeconfig-iap: ## Récupère le kubeconfig (API via tunnel IAP, cf. make tunnel)
	bin/get-kubeconfig.sh --iap

tunnel: ## Ouvre un tunnel IAP vers l'API Kubernetes sur localhost:6443
	gcloud compute start-iap-tunnel "$$($(TF) output -raw instance_name)" 6443 \
	  --local-host-port=localhost:6443 \
	  --project "$$($(TF) output -raw project_id)" \
	  --zone "$$($(TF) output -raw zone)"

## --- GitOps (FluxCD) ---
.PHONY: flux-status flux-reconcile
flux-status: ## État des Kustomizations et HelmReleases Flux
	flux get kustomizations
	flux get helmreleases -A

flux-reconcile: ## Force la synchronisation avec le repo
	flux reconcile kustomization flux-system --with-source

## --- Secrets (hors Git) ---
.PHONY: get-secrets get-grafana-password get-keep-password create-keep-secrets
get-secrets: ## Affiche les URLs et identifiants générés (Grafana, Keep)
	bin/get-secrets.sh all

get-grafana-password: ## Affiche l'URL et le mot de passe admin de Grafana
	bin/get-secrets.sh grafana

get-keep-password: ## Affiche l'URL et le mot de passe admin de Keep
	bin/get-secrets.sh keep

create-keep-secrets: ## Crée les Secrets de Keep et la clé d'API d'Alertmanager (idempotent)
	bin/create-keep-secrets.sh

## --- Qualité ---
.PHONY: fmt lint
fmt: ## Formate le code Terraform
	terraform fmt -recursive infra

lint: ## Vérifie Terraform, shellcheck et les manifests Kubernetes
	terraform fmt -check -recursive infra
	$(TF) init -backend=false -input=false >/dev/null
	$(TF) validate
	shellcheck bin/*.sh bin/fluxcd/*.sh
	bin/validate-manifests.sh
