SHELL := /usr/bin/env bash
TF_DIR := infra/gcp-k3s
TF := terraform -chdir=$(TF_DIR)
export KUBECONFIG ?= $(CURDIR)/.kube/config

.DEFAULT_GOAL := help

.PHONY: help
help: ## Affiche cette aide
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

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
	scripts/get-kubeconfig.sh

kubeconfig-iap: ## Récupère le kubeconfig (API via tunnel IAP, cf. make tunnel)
	scripts/get-kubeconfig.sh --iap

tunnel: ## Ouvre un tunnel IAP vers l'API Kubernetes sur localhost:6443
	gcloud compute start-iap-tunnel "$$($(TF) output -raw instance_name)" 6443 \
	  --local-host-port=localhost:6443 \
	  --project "$$($(TF) output -raw project_id)" \
	  --zone "$$($(TF) output -raw zone)"

## --- Démo ---
.PHONY: demo demo-staging demo-delete
demo: ## Déploie l'app de démo exposée en HTTPS (Let's Encrypt prod)
	scripts/deploy-demo.sh letsencrypt-prod

demo-staging: ## Déploie l'app de démo (Let's Encrypt staging)
	scripts/deploy-demo.sh letsencrypt-staging

demo-delete: ## Supprime l'app de démo
	kubectl delete namespace demo --ignore-not-found

## --- Qualité ---
.PHONY: fmt lint
fmt: ## Formate le code Terraform
	terraform fmt -recursive infra

lint: ## Vérifie format Terraform, validate et shellcheck
	terraform fmt -check -recursive infra
	$(TF) init -backend=false -input=false >/dev/null
	$(TF) validate
	shellcheck scripts/*.sh
