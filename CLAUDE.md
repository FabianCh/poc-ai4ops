# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

POC of agentic AIOps: an AI agent that detects, diagnoses and auto-remediates incidents on a Kubernetes platform.
The platform is a single-node **k3s** cluster on a GCP Compute Engine VM (Terraform), and everything running on
it is deployed by **FluxCD** from the `main` branch (`manifest/flux-system/`). Secrets are encrypted with
**SOPS + age** (`.sops.yaml`) before being committed. Docs and comments are written in French.

## Repository Structure

```
infra/gcp-k3s/         # Terraform: VPC, firewall, static IP, VM + startup script (k3s, cluster-vars ConfigMap)
manifest/
  flux-system/         # FluxCD bootstrap — DO NOT manually edit gotk-sync.yaml/gotk-components.yaml
    base/              # Kustomization CRDs pointing to manifest/base/<component>/
    applications/      # Kustomization CRDs pointing to manifest/applications/<app>/
  base/                # Infrastructure (cert-manager, ClusterIssuers, operators, monitoring...)
  applications/        # Workloads exposed on the cluster
bin/                   # Helper scripts (kubeconfig, flux bootstrap/upgrade, SOPS, manifest validation)
```

## Conventions

- One directory per component under `manifest/base/` or `manifest/applications/`, with a `kustomization.yaml`
  and one file per resource named `<app>-<kind>.yaml` (`-namespace`, `-deployment`, `-service`, `-ingress`,
  `-helmrepository`, `-helmrelease`, `-secret`...).
- Each new component needs a Flux Kustomization `manifest/flux-system/{base,applications}/<app>-ks.yaml`, listed
  in the sibling `kustomization.yaml`. Use `dependsOn` for ordering (applications depend on `cluster-issuers`).
- Helm-based components use a `HelmRepository` + a `HelmRelease` with a pinned chart version.
- Exposure: `Ingress` with `ingressClassName: traefik`, host `<app>.${INGRESS_BASE_DOMAIN}` and annotation
  `cert-manager.io/cluster-issuer: letsencrypt-prod`; the Flux Kustomization must declare
  `postBuild.substituteFrom` the `cluster-vars` ConfigMap.
- **Never commit plaintext secrets**: `bin/encrypt_secret.sh <file>` before staging.

## Checks

```bash
make lint   # terraform fmt/validate, shellcheck, kustomize build + kubeconform on manifest/
```
