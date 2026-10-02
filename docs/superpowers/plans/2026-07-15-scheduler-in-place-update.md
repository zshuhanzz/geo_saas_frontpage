# Cloud Scheduler In-place Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore in-place Cloud Scheduler cron updates and prevent automatic create-and-delete migration during ordinary Admin edits.

**Architecture:** Resolve an existing verified legacy job before the canonical full-UUID job. Update whichever existing job is selected; create a canonical job only when neither exists. Run the synchronous SDK workflow off the FastAPI event loop.

**Tech Stack:** Python 3.11, FastAPI, google-cloud-scheduler, pytest/AnyIO

---

### Task 1: Lock desired resolution behavior with tests

**Files:**
- Modify: `geo_admin/tests/test_gcp_scheduler_tenant_identity.py`

- [ ] Replace the legacy migration assertion with a failing assertion that the verified legacy Job is updated in place and never created or deleted.
- [ ] Add coverage for canonical-only update and neither-existing creation.
- [ ] Run `pytest -q geo_admin/tests/test_gcp_scheduler_tenant_identity.py` and verify the legacy in-place test fails against current production code.

### Task 2: Implement in-place synchronization

**Files:**
- Modify: `geo_admin/src/services/gcp_scheduler.py`

- [ ] Resolve verified legacy first, canonical second, and creation last.
- [ ] Set the outgoing Job name to the resolved existing name before UpdateJob.
- [ ] Remove automatic legacy deletion from ordinary create/update synchronization.
- [ ] Execute the synchronous synchronization workflow with `asyncio.to_thread`.
- [ ] Run the focused scheduler tests and verify they pass.

### Task 3: Regression verification

**Files:**
- Test: `geo_admin/tests/test_gcp_scheduler_workspace_deletion.py`
- Test: `geo_admin/tests/test_scheduler_lifecycle_fence.py`

- [ ] Run all three Scheduler-related test files.
- [ ] Verify the production GCP state contains only the two expected short-name Topteng jobs with schedules matching `geo_clients`.

