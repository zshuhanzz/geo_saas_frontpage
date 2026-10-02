# Cloud SQL Instance — Manual Configuration Reference

> **Status**: NOT managed by Terraform (manual config via GCP Console)
> **Owner**: lancelot (CTO)
> **Last reviewed**: 2026-04-22
>
> The Cloud SQL Postgres instance backing all GEO services was created
> manually during the GCP free-trial period. Configuration changes are
> made through the GCP Console. This file is the single source of truth
> for what's currently set.
>
> A Roadmap entry exists to bring this instance into Terraform management
> via `terraform import` (see `docs/roadmap.md`).

## Identity

| Field | Value |
|---|---|
| Project | `project-90d7849c-de16-4c15-a0a` |
| Region | `us-central1` (Iowa) |
| Instance name | `answer-x-geo-instance` |
| Connection name | `project-90d7849c-de16-4c15-a0a:us-central1:answer-x-geo-instance` |
| Database engine | PostgreSQL 18 |

## Compute & Storage

| Field | Value | Notes |
|---|---|---|
| Edition | `ENTERPRISE_PLUS` | |
| Machine tier | `db-perf-optimized-N-2` | 2 vCPU / 16 GB RAM |
| Storage type | SSD | |
| Storage size | 100 GB | actual data ~365 MB (as of 2026-04-22) |
| Storage auto-resize | Disabled | |
| Availability | `ZONAL` | no HA replica |
| Data Cache | Enabled (~64 GB local SSD, EP-included) | |

## Backup & Recovery

| Field | Value |
|---|---|
| Automated backups | Enabled |
| Backup retention | 14 days |
| Backup window | 02:00-06:00 HKT (UTC 18:00-22:00) |
| Point-in-time recovery | Enabled |
| PITR transaction log retention | 7 days |

## Protection

| Field | Value |
|---|---|
| Prevent instance deletion | **ON** |
| Retain backups after instance deletion | OFF |
| Final backup on deletion | OFF |

## PostgreSQL Flags

| Flag | Value | Reason |
|---|---|---|
| `cloudsql.iam_authentication` | `on` | default Cloud SQL behaviour |
| `work_mem` | `16384` (= 16 MB, unit is KB) | Dashboard `GROUP BY` aggregations on `geo_brand_mentions` were spilling to disk at the 4 MB default. 16 MB covers most analytical queries. |

## Estimated cost (us-central1, Zonal, no HA)

| Component | Hourly | Monthly |
|---|---|---|
| 2 vCPU @ $0.054 | $0.108 | $77.76 |
| 16 GiB RAM @ $0.009 | $0.144 | $103.68 |
| 100 GB SSD @ $0.17/GB-mo | $0.024 | $17.00 |
| ~64 GiB Data Cache @ $0.16/GB-mo | $0.014 | $10.24 |
| Backup storage (~500 MB compressed) | — | ~$0.04 |
| PITR WAL (~100 MB) | — | ~$0.01 |
| **Total** | **~$0.29** | **~$209 (~HKD 1,632)** |

## Change log

| Date | Author | Change | Reason |
|---|---|---|---|
| 2026-04-21 | lancelot | Free-trial → paid (Upgrade Now) | Trial expired |
| 2026-04-21 | lancelot | Tier `N-8` → `N-2` | N-8 was trial default; downsized for actual workload (5-10 clients, 365 MB data, no HA). Saves ~$540/month vs trial spec. |
| 2026-04-21 | lancelot | Backup 14d + PITR 7d enabled | Was disabled in trial; ~$0.05/mo at current data size |
| 2026-04-21 | lancelot | Deletion protection on | Defensive |
| 2026-04-21 | lancelot | `work_mem` flag set to 16 MB | Dashboard query speedup |

---

When updating this file, also re-evaluate whether the `terraform import`
roadmap entry should be promoted in priority.
