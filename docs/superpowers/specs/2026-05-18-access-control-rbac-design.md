# Access Control RBAC Design

Date: 2026-05-18
Status: Draft approved for implementation planning
Scope: AnswerX GEO Admin and SaaS access control

## Goal

Add a production-ready access control foundation for AnswerX GEO before the first customer-facing rollout.

The first release must support:

- Google OAuth based identity for SaaS and Admin.
- Client-level access control for SaaS users.
- Admin-level system roles, including Super Admin and Viewer.
- An explicit `support_all_clients` override for Super Admin users who should also see every client in SaaS.
- Admin UI for managing registered users, client access, and system admins.

The primary security goal is to prevent cross-client data exposure. The UI may improve the experience, but authorization must be enforced on the backend.

## Current State

SaaS and Admin both use Google OAuth in the browser. The frontend decodes the Google credential and stores it in localStorage:

- SaaS stores `geo_saas_token`.
- Admin stores `geo_admin_token`.

Current backend APIs do not consistently verify the Google credential or bind a user identity to a client access policy. The SaaS `/api/clients` endpoint currently returns all clients. Client-scoped API calls accept `client_id` from the request.

This means the current system has tenant-scoped query patterns in many data access paths, but it does not yet have user-to-client authorization.

## Concepts

### Identity

A user is a Google OAuth identity. The stable identity key is Google `sub`; email is still stored and used for Admin search, display, and pre-provisioning.

### SaaS Client Access

Client access controls which SaaS workspaces a user can see and use.

This is not the same as Admin access.

### Admin System Access

Admin access controls whether a user can enter the Admin backend and what they can do there.

Admin system roles:

- `super_admin`: can view and modify Admin configuration.
- `viewer`: can view Admin data but cannot mutate it.

### SaaS All Clients Override

`support_all_clients` is an explicit override on Admin system access.

It means:

- A Super Admin can optionally see all clients in SaaS.
- Super Admin status alone does not grant SaaS access to all clients.
- Viewer users cannot enable this override.

This override must not create rows in the client access table. It is a system-level authorization override checked at runtime.

## Data Model

### `geo_users`

Stores Google OAuth users.

Columns:

- `id uuid primary key`
- `email text not null`
- `google_sub text`
- `name text`
- `avatar_url text`
- `quota_limit integer`
- `is_active boolean not null default true`
- `joined_at timestamptz not null default now()`
- `last_login_at timestamptz`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

Constraints:

- Unique normalized email.
- Unique `google_sub` when present.

Notes:

- `quota_limit` is stored in this release but not enforced yet.
- `email` supports pre-provisioning before first login.
- `google_sub` is populated or updated after successful Google token verification.

### `geo_client_user_access`

Stores SaaS client access.

Columns:

- `id uuid primary key`
- `client_id uuid not null references geo_clients(id)`
- `user_id uuid not null references geo_users(id)`
- `role text not null`
- `is_active boolean not null default true`
- `granted_by uuid references geo_users(id)`
- `granted_at timestamptz not null default now()`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

Initial role values:

- `member`
- `viewer`

First release behavior:

- SaaS treats any active role as client access.
- Fine-grained SaaS editing permissions can be added later without changing the table shape.

Constraints:

- Unique `(client_id, user_id)`.

### `geo_admin_user_access`

Stores Admin system access.

Columns:

- `id uuid primary key`
- `user_id uuid not null references geo_users(id)`
- `role text not null`
- `support_all_clients boolean not null default false`
- `is_active boolean not null default true`
- `granted_by uuid references geo_users(id)`
- `granted_at timestamptz not null default now()`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

Role values:

- `super_admin`
- `viewer`

Constraints:

- Unique `(user_id)`.
- `support_all_clients = true` is only valid when `role = 'super_admin'`.

## Authentication Flow

### Frontend

SaaS and Admin continue using Google OAuth.

After login:

- Store the Google credential locally as today.
- Send it on API calls as `Authorization: Bearer <google_id_token>`.
- Do not rely on frontend-decoded claims for authorization.

### Backend

Both SaaS and Admin backends need a shared auth dependency:

1. Read `Authorization` header.
2. Verify Google ID token against the configured OAuth client ID.
3. Extract `sub`, `email`, `name`, and `picture`.
4. Upsert `geo_users`.
5. Return an authenticated user object to route handlers.

Development bypass can remain for local automation, but production must not accept unsigned or frontend-only identity claims.

## Authorization Rules

### SaaS

SaaS clients list:

- If user has `geo_admin_user_access.role = 'super_admin'` and `support_all_clients = true`, return all active clients.
- Otherwise return only clients with active rows in `geo_client_user_access`.

SaaS client-scoped endpoints:

- Require active access to the requested `client_id`.
- The `support_all_clients` override satisfies this check only for eligible Super Admin users.
- Reject unauthorized access with 403.

Agent endpoints:

- Must also require access to `client_id`.
- Do not trust `client_id` or `user_id` from request body without auth verification.
- Derive the user identity from the verified token.

### Admin

Admin read endpoints:

- Require active `geo_admin_user_access`.
- `super_admin` and `viewer` may read.

Admin mutation endpoints:

- Require active `geo_admin_user_access.role = 'super_admin'`.
- `viewer` receives 403.

Access Control mutation endpoints:

- Require Super Admin.
- A Super Admin cannot accidentally disable or downgrade the last active Super Admin. This prevents lockout.

## Admin UI Design

### Navigation

Add a new sidebar item near Clients:

- Label: `Access Control`
- Route: `/access-control`
- Icon: use a Lucide icon consistent with current sidebar style, such as `ShieldCheck` or `KeyRound`.

### Page Shell

Match existing Admin pages:

- Top title in the same style as Clients, Prompts, and Tasks.
- Short muted description.
- Main body inside `Card`.
- Use `Tabs` for sections.
- Use existing shadcn/Radix components only.
- No native browser dialogs.
- No native HTML select.

Tabs:

1. `Users`
2. `Client Access`
3. `Super Admin`

### Shared Searchable Selector

Create an Admin UI component:

`SearchableEntitySelect`

Use it for:

- User selection.
- Client selection.
- Filterable dropdowns where the option list can grow.

Behavior:

- Opens a custom dropdown panel.
- Contains an inline search input.
- Filters options as the user types.
- Shows loading and empty states.
- Allows selecting an item from the dropdown.
- Uses project Button/Input/Card/Badge styling.

This component replaces any native select-like interaction for user and client picking.

### Users Tab

Purpose: manage registered Google users.

Toolbar:

- Search users by email or name.
- Status filter.
- `Add User` button.

Table columns:

- Email
- Name
- Joined At
- Quota Limit
- Status
- Actions

Actions:

- Add user
- Edit user
- Disable user

Dialog fields:

- Email
- Name
- Quota Limit
- Active status

Notes:

- `google_sub` is not manually edited.
- A user can be pre-provisioned by email before first login.

### Client Access Tab

Purpose: grant SaaS access to specific clients.

Toolbar:

- Search by user email, user name, or client name.
- Client filter using searchable selector.
- Role filter.
- Status filter.
- `Grant Access` button.

Table columns:

- Email
- Name
- Client
- Role
- Status
- Granted At
- Actions

Actions:

- Grant access
- Change role
- Revoke or disable access

Dialog fields:

- User selector
- Client selector
- Role
- Active status

Notes:

- This tab controls normal SaaS access.
- It does not include the Super Admin all-clients override.

### Super Admin Tab

Purpose: manage Admin system access.

Toolbar:

- Search admins by email or name.
- Role filter.
- Status filter.
- `Add Admin` button.

Table columns:

- Email
- Name
- System Role
- SaaS All Clients
- Status
- Granted At
- Actions

`SaaS All Clients` display:

- `Enabled` badge when `support_all_clients = true`.
- `Disabled` badge otherwise.

Dialog fields:

- User selector
- System role
- Switch: `Allow SaaS access to all clients`
- Active status

Switch behavior:

- Enabled only when role is `super_admin`.
- Disabled and false when role is `viewer`.

Helper text:

`Lets this admin switch across all client workspaces in the SaaS app. Admin role alone does not grant SaaS client access.`

## API Design

### Auth

Shared current-user endpoint:

- `GET /api/auth/me`

Returns:

- User identity.
- SaaS accessible clients count.
- Admin role if any.
- `support_all_clients`.

### SaaS

Update:

- `GET /api/clients`

Behavior:

- Requires authenticated user.
- Returns only authorized clients, unless `support_all_clients` applies.

Every SaaS route with `client_id`:

- Add `require_client_access`.

### Admin

Add router:

- Prefix: `/api/access-control`

Endpoints:

- `GET /users`
- `POST /users`
- `PATCH /users/{user_id}`
- `GET /client-access`
- `POST /client-access`
- `PATCH /client-access/{access_id}`
- `DELETE /client-access/{access_id}`
- `GET /admin-access`
- `POST /admin-access`
- `PATCH /admin-access/{access_id}`
- `DELETE /admin-access/{access_id}`

All write endpoints require Super Admin.

## Bootstrap

The system needs one initial Super Admin.

Recommended bootstrap:

- Add a migration seed for the CTO email.
- Also support `BOOTSTRAP_SUPER_ADMIN_EMAILS` as an environment fallback.

Rules:

- The bootstrap user is inserted into `geo_users`.
- The bootstrap user receives `geo_admin_user_access.role = 'super_admin'`.
- `support_all_clients` can be true for the bootstrap user if desired.

## Error Handling

SaaS:

- No accessible clients: show a friendly empty state telling the user to contact the AnswerX team.
- Unauthorized client: backend returns 403; frontend should clear invalid selected client if it is no longer in the returned client list.

Admin:

- Viewer mutation attempt: show a non-destructive error toast.
- Last active Super Admin mutation attempt: reject with a clear message.
- Duplicate grant: update the existing row or show a clear conflict message.

## Testing Plan

Backend tests:

- Google token verification dependency can be tested through a mock verifier.
- User upsert by email and Google sub.
- SaaS `/api/clients` returns only authorized clients.
- `support_all_clients` returns all clients only for Super Admin.
- Viewer cannot mutate Admin resources.
- Last Super Admin cannot be disabled.
- Agent endpoints reject unauthorized client IDs.

Frontend verification:

- Admin Access Control page matches existing Admin page density and styling.
- Searchable user and client selectors support typing, empty state, and selection.
- No native browser dialogs or native selects.
- SaaS workspace selector only shows authorized clients.
- Saved localStorage client selection is ignored if it is no longer authorized.

Manual multi-tenant verification:

- User A has access to Client A only.
- User B has access to Client B only.
- User A cannot load Client B through UI or direct API requests.
- Super Admin without `support_all_clients` cannot see all clients in SaaS.
- Super Admin with `support_all_clients` can see all clients in SaaS.
- Admin Viewer can read Admin pages but cannot mutate data.

## Implementation Notes

- Provide SQL migration files only. Do not run DDL directly.
- Keep auth and authorization helpers shared where practical, but avoid coupling Admin UI behavior into SaaS business logic.
- Do not hardcode production user emails in application code. Use migration seed or environment bootstrap.
- Preserve existing Admin visual language and component patterns.
- Keep Super Admin and Client Access as separate authorization concepts.
