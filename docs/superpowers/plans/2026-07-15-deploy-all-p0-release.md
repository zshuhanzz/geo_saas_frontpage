# P0 Iteration Deployment Script Update Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update `deploy_all.sh` so the P0 iteration deploys only the changed Admin and SaaS services with incremented image tags.

**Architecture:** `geo_common` changes are bundled into the Admin API and SaaS API root-context Docker builds, so it has no standalone image. Collector, Analyzer, and Agent remain defined in the script but their build, push, and Terraform commands stay commented out.

**Tech Stack:** Bash, Google Cloud Build, Artifact Registry, Terraform, Cloud Run.

---

### Task 1: Update release scope and versions

**Files:**
- Modify: `deploy_all.sh`

- [ ] Increment Admin API/Web and SaaS API/Web image versions by one.
- [ ] Enable Admin and SaaS `terraform.tfvars` image synchronization.
- [ ] Enable Admin and SaaS image builds and Terraform applies.
- [ ] Preserve Collector, Analyzer, and Agent commands as commented deployment templates.
- [ ] Update console summaries so the enabled and skipped service lists match execution.

### Task 2: Verify the script without deploying

**Files:**
- Test: `deploy_all.sh`

- [ ] Run `bash -n deploy_all.sh`; expect exit code 0 and no output.
- [ ] Inspect active `gcloud builds submit` and `terraform apply` commands; expect only Admin and SaaS deployment commands to be executable.
- [ ] Inspect version variables; expect Admin API `v27`, Admin Web `v30`, SaaS API `v67`, and SaaS Web `v95`.
