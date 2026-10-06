# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

POC of agentic AIOps: an AI agent that detects, diagnoses and auto-remediates incidents on a Kubernetes platform.
The platform is a single-node **k3s** cluster on a GCP Compute Engine VM (Terraform), and everything running on
it is deployed by **FluxCD** from the `main` branch (`manifest/flux-system/`). Goal: as few manual steps as
possible — `terraform apply` alone brings up k3s, installs Flux (startup script) and syncs this **public** repo
over HTTPS. Docs and comments are written in French.

## Repository Structure

```
infra/gcp-k3s/         # Terraform: VPC, firewall, static IP, VM + startup script (k3s, cluster-vars, Flux install)
manifest/
  flux-system/         # FluxCD bootstrap — DO NOT manually edit gotk-sync.yaml/gotk-components.yaml
    base/              # Kustomization CRDs pointing to manifest/base/<component>/
    applications/      # Kustomization CRDs pointing to manifest/applications/<app>/
  base/                # Infrastructure (cert-manager, ClusterIssuers, operators, monitoring...)
  applications/        # Workloads exposed on the cluster
ia4ops-agent/          # AI diagnosis agent (Python 3.14, uv, FastAPI + LangGraph) + Dockerfile
                       # image built/pushed to ghcr.io by .github/workflows/ia4ops-agent.yml on main
bin/                   # Helper scripts (kubeconfig, flux upgrade, manifest validation, create-keep-secrets, get-secrets)
```

## Conventions

- One directory per component under `manifest/base/` or `manifest/applications/`, with a `kustomization.yaml`
  and one file per resource named `<app>-<kind>.yaml` (`-namespace`, `-deployment`, `-service`, `-ingress`,
  `-helmrepository`, `-helmrelease`...).
- Each new component needs a Flux Kustomization `manifest/flux-system/{base,applications}/<app>-ks.yaml`, listed
  in the sibling `kustomization.yaml`. Use `dependsOn` for ordering (applications depend on `cluster-issuers`).
- Helm-based components use a `HelmRepository` + a `HelmRelease` with a pinned chart version.
- Exposure: `Ingress` with `ingressClassName: traefik`, host `<app>.${INGRESS_BASE_DOMAIN}` and annotation
  `cert-manager.io/cluster-issuer: letsencrypt-prod`; the Flux Kustomization must declare
  `postBuild.substituteFrom` the `cluster-vars` ConfigMap.
- The repo is public and there is no secret management (POC): never commit secrets or credentials. Secrets
  a workload needs (e.g. Keep) are created out of Git by a script in `bin/` (`make keep-secrets`) and
  referenced by name in the manifests; pods wait for them rather than starting unprotected.

## Checks

```bash
make lint   # terraform fmt/validate, shellcheck, kustomize build + kubeconform on manifest/
cd ia4ops-agent && uv sync --locked --extra dev && uv run pytest   # agent tests
```

`manifest/` only holds Kubernetes manifests deployed by Flux: application source code lives in its
own top-level directory (e.g. `ia4ops-agent/`).
