# Access Control RBAC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Google OAuth based Admin/SaaS access control with client-level SaaS RBAC, Admin Super Admin/Viewer roles, and an explicit `support_all_clients` override.

**Architecture:** Add the RBAC schema in migration 059, then implement a shared auth/access service used by SaaS, Admin, and Agent. SaaS and Agent enforce client access at every `client_id` boundary; Admin enforces system role access globally and exposes Access Control management UI.

**Tech Stack:** PostgreSQL, FastAPI, asyncpg, Google OAuth ID token verification, React/TypeScript, Radix/shadcn UI components.

---

## Scope Guard

This plan does not execute DDL. The SQL is written in `migrations/059_access_control_rbac.sql` for manual Cloud SQL execution.

This plan does not implement user quota enforcement. `geo_users.quota_limit` is stored only.

This plan keeps Admin system access and SaaS client access separate. `support_all_clients` is a Super Admin-only SaaS override and does not create client access rows.

## File Map

### Already Created

- `migrations/059_access_control_rbac.sql`: Creates `geo_users`, `geo_client_user_access`, `geo_admin_user_access`, indexes, constraints, and updated_at triggers.

### Backend Shared Auth

- Create: `geo_common/src/geo_common/auth/__init__.py`
- Create: `geo_common/src/geo_common/auth/access_control.py`
- Modify: `geo_saas/src/requirements.txt`
- Modify: `geo_admin/src/requirements.txt`
- Modify: `geo_agent/src/requirements.txt`

### SaaS Backend

- Create: `geo_saas/src/dependencies/__init__.py`
- Create: `geo_saas/src/dependencies/auth.py`
- Modify: `geo_saas/src/main.py`
- Modify: `geo_saas/src/routers/clients.py`
- Modify all SaaS routers that accept `client_id`.

High-risk route groups:

- `geo_saas/src/routers/prompts.py`
- `geo_saas/src/routers/brainstorming.py`
- `geo_saas/src/routers/settings/*.py`
- `geo_saas/src/routers/insights/*.py`
- `geo_saas/src/routers/sentiment.py`
- `geo_saas/src/routers/onboarding/*.py`

### Agent Backend

- Create: `geo_agent/src/dependencies/__init__.py`
- Create: `geo_agent/src/dependencies/auth.py`
- Modify: `geo_agent/src/main.py`

### Admin Backend

- Create: `geo_admin/src/dependencies/__init__.py`
- Create: `geo_admin/src/dependencies/auth.py`
- Create: `geo_admin/src/routers/access_control.py`
- Modify: `geo_admin/src/main.py`

### SaaS Frontend

- Modify: `geo_saas/web/src/contexts/AuthContext.tsx`
- Create or restore if missing: `geo_saas/web/src/lib/api.ts`
- Modify: `geo_saas/web/src/contexts/SaaSContext.tsx`
- Modify Agent pages and helpers that pass `userId` manually.

### Admin Frontend

- Modify: `geo_admin/web/src/contexts/AuthContext.tsx`
- Modify: `geo_admin/web/src/api/client.ts`
- Modify: `geo_admin/web/src/components/layout/Sidebar.tsx`
- Modify: `geo_admin/web/src/App.tsx`
- Create: `geo_admin/web/src/components/access-control/SearchableEntitySelect.tsx`
- Create: `geo_admin/web/src/pages/AccessControlPage.tsx`

---

## Task 0: Database Migration File

**Files:**

- Created: `migrations/059_access_control_rbac.sql`

- [x] **Step 1: Add SQL schema migration**

Migration file creates:

- `geo_users`
- `geo_client_user_access`
- `geo_admin_user_access`
- lower-email unique index
- Google subject unique index
- role checks
- `support_all_clients` Super Admin-only check
- active access indexes
- `updated_at` triggers

- [ ] **Step 2: Manual SQL review**

Run:

```bash
sed -n '1,260p' migrations/059_access_control_rbac.sql
```

Expected:

- No hardcoded customer data.
- No destructive DDL.
- Ends with manual verification queries in comments.

Manual execution is owned by the CTO in Cloud SQL.

---

## Task 1: Shared Auth and Access Service

**Files:**

- Create: `geo_common/src/geo_common/auth/__init__.py`
- Create: `geo_common/src/geo_common/auth/access_control.py`
- Modify: `geo_saas/src/requirements.txt`
- Modify: `geo_admin/src/requirements.txt`
- Modify: `geo_agent/src/requirements.txt`
- Test: `geo_common/tests/test_access_control.py`

- [ ] **Step 1: Add dependency**

Add to all three backend requirements files:

```text
google-auth>=2.0.0
```

- [ ] **Step 2: Write shared auth models and functions**

Create `geo_common/src/geo_common/auth/access_control.py` with these responsibilities:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

AdminRole = Literal["super_admin", "viewer"]
ClientRole = Literal["member", "viewer"]


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str
    google_sub: str | None
    name: str | None
    avatar_url: str | None
    is_active: bool


@dataclass(frozen=True)
class AdminAccess:
    role: AdminRole
    support_all_clients: bool
    is_active: bool


def normalize_email(email: str) -> str:
    return email.strip().lower()


def verify_google_id_token(token: str, google_client_id: str) -> dict[str, Any]:
    claims = id_token.verify_oauth2_token(
        token,
        google_requests.Request(),
        google_client_id,
    )
    if not claims.get("email"):
        raise ValueError("Google token does not contain email")
    return claims
```

Add async DB functions:

```python
async def upsert_google_user(pool, claims: dict[str, Any]) -> AuthenticatedUser:
    email = normalize_email(str(claims["email"]))
    row = await pool.fetchrow(
        """
        INSERT INTO geo_users (email, google_sub, name, avatar_url, last_login_at)
        VALUES ($1, $2, $3, $4, NOW())
        ON CONFLICT (LOWER(email)) DO UPDATE SET
            google_sub = COALESCE(EXCLUDED.google_sub, geo_users.google_sub),
            name = COALESCE(EXCLUDED.name, geo_users.name),
            avatar_url = COALESCE(EXCLUDED.avatar_url, geo_users.avatar_url),
            last_login_at = NOW(),
            updated_at = NOW()
        RETURNING id, email, google_sub, name, avatar_url, is_active
        """,
        email,
        claims.get("sub"),
        claims.get("name"),
        claims.get("picture"),
    )
    return AuthenticatedUser(
        id=str(row["id"]),
        email=row["email"],
        google_sub=row["google_sub"],
        name=row["name"],
        avatar_url=row["avatar_url"],
        is_active=row["is_active"],
    )
```

Add access checks:

```python
async def get_admin_access(pool, user_id: str) -> AdminAccess | None:
    row = await pool.fetchrow(
        """
        SELECT role, support_all_clients, is_active
        FROM geo_admin_user_access
        WHERE user_id = $1::uuid
        """,
        user_id,
    )
    if not row:
        return None
    return AdminAccess(
        role=row["role"],
        support_all_clients=row["support_all_clients"],
        is_active=row["is_active"],
    )


async def has_support_all_clients(pool, user_id: str) -> bool:
    row = await pool.fetchrow(
        """
        SELECT 1
        FROM geo_admin_user_access
        WHERE user_id = $1::uuid
          AND role = 'super_admin'
          AND support_all_clients = true
          AND is_active = true
        """,
        user_id,
    )
    return row is not None


async def has_client_access(pool, user_id: str, client_id: str) -> bool:
    if await has_support_all_clients(pool, user_id):
        return True
    row = await pool.fetchrow(
        """
        SELECT 1
        FROM geo_client_user_access
        WHERE user_id = $1::uuid
          AND client_id = $2::uuid
          AND is_active = true
        """,
        user_id,
        client_id,
    )
    return row is not None
```

- [ ] **Step 3: Write tests**

Create `geo_common/tests/test_access_control.py` for pure helpers:

```python
from geo_common.auth.access_control import normalize_email


def test_normalize_email_lowercases_and_trims():
    assert normalize_email("  User@Example.COM ") == "user@example.com"
```

DB-backed checks can be covered in service tests with fake pool objects.

- [ ] **Step 4: Run tests**

Run:

```bash
cd geo_common && pytest tests/test_access_control.py -v
```

Expected:

- PASS.

---

## Task 2: FastAPI Auth Dependencies

**Files:**

- Create: `geo_saas/src/dependencies/auth.py`
- Create: `geo_admin/src/dependencies/auth.py`
- Create: `geo_agent/src/dependencies/auth.py`
- Modify: `geo_saas/src/main.py`
- Modify: `geo_admin/src/main.py`
- Modify: `geo_agent/src/main.py`

- [ ] **Step 1: Implement current-user dependency per service**

Each service dependency should:

- Read `Authorization`.
- Reject missing/invalid bearer tokens.
- Verify Google token against `GOOGLE_CLIENT_ID`.
- Upsert `geo_users`.
- Reject inactive users.

Shared dependency shape:

```python
import os
from fastapi import Depends, Header, HTTPException, status
from geo_common.auth.access_control import (
    AuthenticatedUser,
    upsert_google_user,
    verify_google_id_token,
)
from pool import get_pool


async def get_current_user(
    authorization: str | None = Header(default=None),
    pool=Depends(get_pool),
) -> AuthenticatedUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    google_client_id = os.environ.get("GOOGLE_CLIENT_ID")
    if not google_client_id:
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID is not configured")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = verify_google_id_token(token, google_client_id)
        user = await upsert_google_user(pool, claims)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google token")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is disabled")
    return user
```

- [ ] **Step 2: Add Admin dependencies**

In `geo_admin/src/dependencies/auth.py`, add:

```python
from fastapi import Depends, HTTPException, status
from geo_common.auth.access_control import AuthenticatedUser, get_admin_access
from pool import get_pool


async def require_admin_user(
    user: AuthenticatedUser = Depends(get_current_user),
    pool=Depends(get_pool),
) -> AuthenticatedUser:
    access = await get_admin_access(pool, user.id)
    if not access or not access.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


async def require_super_admin(
    user: AuthenticatedUser = Depends(get_current_user),
    pool=Depends(get_pool),
) -> AuthenticatedUser:
    access = await get_admin_access(pool, user.id)
    if not access or not access.is_active or access.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super Admin access required")
    return user
```

- [ ] **Step 3: Add SaaS/Agent client access dependency**

In SaaS and Agent dependency modules, add:

```python
from fastapi import Depends, HTTPException, Request, status
from geo_common.auth.access_control import AuthenticatedUser, has_client_access
from pool import get_pool


def resolve_client_id_from_request(request: Request) -> str | None:
    if "client_id" in request.path_params:
        return str(request.path_params["client_id"])
    if "client_id" in request.query_params:
        return request.query_params["client_id"]
    return None


async def require_client_access(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    pool=Depends(get_pool),
) -> AuthenticatedUser:
    client_id = resolve_client_id_from_request(request)
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id is required for access check")
    if not await has_client_access(pool, user.id, client_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Client access denied")
    return user
```

For body-only endpoints, call `has_client_access(pool, user.id, body.client_id)` inside the route.

---

## Task 3: SaaS Client Access Enforcement

**Files:**

- Modify: `geo_saas/src/routers/clients.py`
- Modify: all SaaS routes with `client_id`
- Test: `geo_saas/tests/test_access_control_clients.py`

- [ ] **Step 1: Filter `/api/clients` by current user**

Change `list_accessible_clients` to depend on current user and select:

```sql
SELECT c.id, c.name, c.client_prompt_quota,
       c.config_platforms, c.config_countries, c.config_languages
FROM geo_clients c
WHERE EXISTS (
    SELECT 1
    FROM geo_client_user_access cua
    WHERE cua.client_id = c.id
      AND cua.user_id = $1::uuid
      AND cua.is_active = true
)
OR EXISTS (
    SELECT 1
    FROM geo_admin_user_access aua
    WHERE aua.user_id = $1::uuid
      AND aua.role = 'super_admin'
      AND aua.support_all_clients = true
      AND aua.is_active = true
)
ORDER BY c.name
```

- [ ] **Step 2: Add route checks**

For each SaaS route with `client_id` in path or query, add:

```python
_user=Depends(require_client_access)
```

For body-only endpoints such as brainstorming generation, explicitly check:

```python
user = Depends(get_current_user)
pool = Depends(get_pool)
if not await has_client_access(pool, user.id, str(body.client_id)):
    raise HTTPException(status_code=403, detail="Client access denied")
```

- [ ] **Step 3: Coverage grep**

Run:

```bash
rg -n "client_id" geo_saas/src/routers
```

Expected:

- Every route accepting `client_id` has either dependency-based or explicit access enforcement.

- [ ] **Step 4: Tests**

Add tests that prove:

- User A sees only Client A.
- User B sees only Client B.
- Super Admin with `support_all_clients` sees all clients.
- Super Admin without `support_all_clients` does not see all clients.
- Direct request to unauthorized client returns 403.

---

## Task 4: Agent Access Enforcement

**Files:**

- Modify: `geo_agent/src/main.py`
- Modify: `geo_saas/web/src/pages/agents/AgentChat.tsx`
- Modify: `geo_saas/web/src/pages/agents/AgentChat.parts/useAgentChatStream.ts`
- Modify other Agent frontend helpers using `userId`

- [ ] **Step 1: Require auth on Agent endpoints**

All Agent endpoints that accept `client_id` must require current user.

For `ChatRequest`, stop trusting request `user_id`. Derive:

```python
user_identifier = f"google:{user.google_sub}" if user.google_sub else f"email:{user.email}"
```

Then use `user_identifier` for:

- sessions
- messages
- memories
- token usage
- rate limiting

- [ ] **Step 2: Check `client_id` before any rate limit or DB load**

In `/api/agent/chat`, the first security step must be:

```python
if not await has_client_access(pool, user.id, data.client_id):
    raise HTTPException(status_code=403, detail="Client access denied")
```

This check must happen before:

- `check_rate_limit`
- `_load_client_context`
- `_upsert_session`
- `load_memories`

- [ ] **Step 3: Update frontend Agent calls**

Remove manual trust in `userId` for authorization. The frontend may continue passing a user identifier temporarily for backward compatibility, but backend must ignore it for security.

All Agent fetches must include:

```ts
Authorization: `Bearer ${localStorage.getItem("geo_saas_token")}`
```

- [ ] **Step 4: Tests**

Add tests for:

- Unauthorized user cannot chat with another client.
- Session list for unauthorized client returns 403.
- Existing thread cannot be loaded by another user/client pair.

---

## Task 5: Admin Auth, Viewer Guard, and Access Control API

**Files:**

- Create: `geo_admin/src/routers/access_control.py`
- Modify: `geo_admin/src/main.py`
- Test: `geo_admin/tests/test_access_control_api.py`

- [ ] **Step 1: Add Admin global auth middleware or dependencies**

Admin `/api/*` routes must require Admin access.

Recommended first implementation:

- Add a middleware that authenticates all `/api/*` requests.
- Allow `GET`, `HEAD`, and `OPTIONS` for `super_admin` and `viewer`.
- Allow mutations only for `super_admin`.

Pseudo-shape:

```python
READ_METHODS = {"GET", "HEAD", "OPTIONS"}

@app.middleware("http")
async def admin_access_middleware(request: Request, call_next):
    if not request.url.path.startswith("/api/"):
        return await call_next(request)
    user = await authenticate_request_from_header(request)
    access = await load_admin_access(user.id)
    if not access or not access.is_active:
        return JSONResponse({"detail": "Admin access required"}, status_code=403)
    if request.method not in READ_METHODS and access.role != "super_admin":
        return JSONResponse({"detail": "Super Admin access required"}, status_code=403)
    request.state.user = user
    request.state.admin_access = access
    return await call_next(request)
```

- [ ] **Step 2: Implement Access Control router**

Create endpoints:

- `GET /api/access-control/users`
- `POST /api/access-control/users`
- `PATCH /api/access-control/users/{user_id}`
- `GET /api/access-control/client-access`
- `POST /api/access-control/client-access`
- `PATCH /api/access-control/client-access/{access_id}`
- `DELETE /api/access-control/client-access/{access_id}`
- `GET /api/access-control/admin-access`
- `POST /api/access-control/admin-access`
- `PATCH /api/access-control/admin-access/{access_id}`
- `DELETE /api/access-control/admin-access/{access_id}`

Deletion should soft-disable by setting `is_active = false`.

- [ ] **Step 3: Prevent last Super Admin lockout**

Before disabling or downgrading a Super Admin, check:

```sql
SELECT COUNT(*)
FROM geo_admin_user_access
WHERE role = 'super_admin'
  AND is_active = true
```

Reject if the target mutation would reduce the count to zero.

- [ ] **Step 4: Bootstrap path**

Implement `BOOTSTRAP_SUPER_ADMIN_EMAILS` support in Admin auth dependency:

- If a verified Google user email is in the env list, ensure `geo_admin_user_access` exists with `role = 'super_admin'`.
- This avoids hardcoding emails in code and avoids seeding data in migration.

---

## Task 6: Frontend API Auth Headers

**Files:**

- Modify: `geo_saas/web/src/contexts/AuthContext.tsx`
- Create or restore: `geo_saas/web/src/lib/api.ts`
- Modify: `geo_admin/web/src/contexts/AuthContext.tsx`
- Modify: `geo_admin/web/src/api/client.ts`

- [ ] **Step 1: Expose token from AuthContext**

Add `token` to AuthContext values for SaaS and Admin:

```ts
interface AuthContextType {
  user: User | null;
  token: string | null;
  loading: boolean;
  login: (credential: string) => { success: boolean; error?: string };
  logout: () => void;
}
```

- [ ] **Step 2: Add auth headers in fetch helpers**

SaaS and Admin fetch helpers should include:

```ts
const token = localStorage.getItem("geo_saas_token");
const authHeaders = token ? { Authorization: `Bearer ${token}` } : {};
```

Admin uses `geo_admin_token`.

- [ ] **Step 3: Handle 401/403**

For 401:

- Clear the local token.
- Send the user back to login.

For 403:

- Show a non-destructive error state or toast.
- Do not fall back to showing all clients.

---

## Task 7: SaaS Workspace Selector Behavior

**Files:**

- Modify: `geo_saas/web/src/contexts/SaaSContext.tsx`
- Modify: `geo_saas/web/src/components/layout/Header.tsx`
- Modify any workspace selector component if separate.

- [ ] **Step 1: Filter comes from backend only**

Do not client-side hide unauthorized clients. Trust `/api/clients` to return only authorized rows.

- [ ] **Step 2: Invalidate unauthorized saved client**

Current behavior already validates saved client against returned clients. Keep this behavior:

```ts
const savedClientId = localStorage.getItem("geo_saas_client_id");
const validSaved = data?.find((c) => c.id === savedClientId);
```

If no valid saved client exists, select the first returned authorized client.

- [ ] **Step 3: Empty state**

If no clients are returned:

- Do not route into dashboards that require `clientId`.
- Show a friendly empty state: contact AnswerX team for workspace access.

---

## Task 8: Admin Access Control UI

**Files:**

- Create: `geo_admin/web/src/components/access-control/SearchableEntitySelect.tsx`
- Create: `geo_admin/web/src/pages/AccessControlPage.tsx`
- Modify: `geo_admin/web/src/components/layout/Sidebar.tsx`
- Modify: `geo_admin/web/src/App.tsx`
- Modify: `geo_admin/web/src/api/client.ts`
- Regenerate if used: `geo_admin/web/src/api/openapi.d.ts`

- [ ] **Step 1: Add API client functions**

Add functions:

```ts
export async function listAccessControlUsers(params: URLSearchParams): Promise<UserListOut> {}
export async function createAccessControlUser(data: UserCreate): Promise<UserOut> {}
export async function updateAccessControlUser(userId: string, data: UserUpdate): Promise<UserOut> {}
export async function listClientAccess(params: URLSearchParams): Promise<ClientAccessListOut> {}
export async function createClientAccess(data: ClientAccessCreate): Promise<ClientAccessOut> {}
export async function updateClientAccess(accessId: string, data: ClientAccessUpdate): Promise<ClientAccessOut> {}
export async function deleteClientAccess(accessId: string): Promise<void> {}
export async function listAdminAccess(params: URLSearchParams): Promise<AdminAccessListOut> {}
export async function createAdminAccess(data: AdminAccessCreate): Promise<AdminAccessOut> {}
export async function updateAdminAccess(accessId: string, data: AdminAccessUpdate): Promise<AdminAccessOut> {}
export async function deleteAdminAccess(accessId: string): Promise<void> {}
```

- [ ] **Step 2: Build `SearchableEntitySelect`**

Component requirements:

- Uses project `Input`, `Button`, `Badge`, and card-like dropdown styling.
- No native select.
- Search input inside dropdown.
- Loading state.
- Empty state.
- Keyboard selection preferred if time allows.

- [ ] **Step 3: Build Access Control page**

Use the same visual language as existing Admin pages:

- `text-3xl font-bold tracking-tight`
- muted description
- `Card`
- `Tabs`
- `Table`
- `Dialog`
- `Button`
- `Badge`

Tabs:

- Users
- Client Access
- Super Admin

- [ ] **Step 4: Super Admin UI**

Super Admin table must include:

- Email
- Name
- System Role
- SaaS All Clients
- Status
- Granted At
- Actions

Add/Edit dialog includes:

- User selector
- System role
- Switch: `Allow SaaS access to all clients`
- Active status

When role is `viewer`, force `support_all_clients = false` and disable the switch.

- [ ] **Step 5: Navigation**

Add sidebar item near Clients:

```ts
{ name: "Access Control", href: "/access-control", icon: ShieldCheck }
```

Add route:

```tsx
<Route path="/access-control" element={<AccessControlPage />} />
```

---

## Task 9: Verification

**Files:**

- No new implementation files unless test utilities are needed.

- [ ] **Step 1: Backend type/import smoke checks**

Run:

```bash
python -m compileall geo_common/src geo_saas/src geo_admin/src geo_agent/src
```

Expected:

- No syntax errors.

- [ ] **Step 2: Backend tests**

Run targeted tests:

```bash
cd geo_common && pytest tests/test_access_control.py -v
```

Then run service tests if available:

```bash
pytest geo_admin/tests geo_common/tests -v
```

Expected:

- New auth/access tests pass.
- Existing tests either pass or failures are documented as unrelated.

- [ ] **Step 3: Frontend typechecks**

Run:

```bash
cd geo_admin/web && npm run typecheck
cd ../../geo_saas/web && npm run typecheck
```

Expected:

- TypeScript passes.

- [ ] **Step 4: Manual tenant isolation test**

After Cloud SQL migration and seed/admin setup:

1. Create Client A and Client B.
2. Create User A and User B.
3. Grant User A only Client A.
4. Grant User B only Client B.
5. Login as User A in SaaS.
6. Confirm only Client A appears.
7. Directly request Client B APIs as User A.
8. Confirm 403.
9. Enable Super Admin for an internal user with `support_all_clients = false`.
10. Confirm Admin access works but SaaS does not show all clients.
11. Enable `support_all_clients = true`.
12. Confirm SaaS shows all clients.

---

## Task 10: Implementation Order

Recommended execution order:

1. Apply migration manually in Cloud SQL.
2. Implement shared auth/access service.
3. Add backend auth dependencies.
4. Protect SaaS `/api/clients`.
5. Protect SaaS client-scoped routes.
6. Protect Agent endpoints.
7. Protect Admin APIs.
8. Add Access Control API.
9. Add frontend auth headers.
10. Add Admin Access Control UI.
11. Run verification.

Do not start Admin UI before backend access APIs are stable, because the page depends on the exact response shapes and permission errors.

## Self-Review

Spec coverage:

- Google OAuth identity: covered in Tasks 1, 2, and 6.
- SaaS Client Access: covered in Tasks 3, 4, and 7.
- Super Admin and Viewer: covered in Tasks 5 and 8.
- `support_all_clients`: covered in migration, Tasks 1, 3, 5, and 8.
- Admin UI style and no native controls: covered in Task 8.
- No direct DDL execution: covered in Task 0 and Scope Guard.

No placeholders are intentionally left in this plan. If a worker finds a route accepting `client_id` without enforcement during Task 3 coverage grep, that route must be added to the Task 3 route-check list before implementation is considered complete.
