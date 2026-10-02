# OpenAPI → TypeScript codegen

Phase 7 (2026-04-25). The frontend types for FastAPI request/response shapes are generated from each backend's `/openapi.json` schema rather than hand-maintained.

## Why

Before Phase 7, every endpoint that the frontend consumed had a hand-written TypeScript type next to the call site. When a backend Pydantic model gained a field, the frontend type drifted silently — the field would arrive as `unknown` until someone manually updated the `.ts` definition. Multiply by ~200 endpoints across `geo_saas` + `geo_admin` and the drift was guaranteed.

`openapi-typescript` reads the `/openapi.json` exposed by every FastAPI app and emits a single `.d.ts` of strictly-typed `paths` + `components.schemas`. Frontend code imports from there:

```ts
import type { paths, components } from "@/api/openapi";

type Brand = components["schemas"]["BrandOut"];
type ListBrandsResponse =
    paths["/api/settings/brands"]["get"]["responses"]["200"]["content"]["application/json"];
```

When a backend model changes, regenerating the `.d.ts` causes the frontend to fail typecheck at every drift site. No silent drift.

## Prerequisites

OpenAPI codegen is only as accurate as the FastAPI schema it reads. Every endpoint must declare `response_model=` on the route decorator and define the request body via Pydantic `BaseModel`. The reference template lives at:

- `geo_admin/src/routers/languages.py` — full `response_model=` + per-endpoint Pydantic shapes.

The Phase 4 follow-up sweep is annotating the remaining 195 endpoints. Run codegen *after* that sweep merges, otherwise the generated types will be `unknown`-heavy.

## Backend endpoints

Each module exposes its own `/openapi.json` on its dev port:

| Module | Dev port | OpenAPI URL |
|---|---|---|
| geo_admin | 8000 | http://localhost:8000/openapi.json |
| geo_saas | 8001 | http://localhost:8001/openapi.json |
| geo_agent | 8002 | http://localhost:8002/openapi.json |

Each module is a standalone FastAPI app on its own port:
- `geo_admin/web` proxies `/api/*` to `localhost:8000` (admin backend).
- `geo_saas/web` proxies `/api/*` to `localhost:8001` (saas backend) and `/api/agent/*` to `localhost:8002` (agent backend).

## Generating types

### geo_saas/web

```bash
# Both FastAPI dev servers must be running:
cd geo_saas/src && APP_ENV=local ./venv/bin/uvicorn main:app --reload --port 8001 --env-file .env.local &
cd geo_agent/src && APP_ENV=local ./venv/bin/uvicorn main:app --reload --port 8002 --env-file .env.local &

# Then from saas/web/:
cd geo_saas/web
npm install               # one-time, lands openapi-typescript
npm run gen:api           # writes src/api/openapi.d.ts (saas) + openapi-agent.d.ts (agent)
```

### geo_admin/web

```bash
cd geo_admin/src && APP_ENV=local ./venv/bin/uvicorn main:app --reload --port 8000 --env-file .env.local &

cd geo_admin/web
npm install
npm run gen:api           # writes src/api/openapi.d.ts
```

## Workflow rules

1. **Generated files are committed.** Anyone checking out the repo gets the latest types without running a backend. The `.d.ts` is treated like a lockfile — diff-reviewable, and a regeneration is its own commit.
2. **Regenerate after every backend Pydantic model change.** If the diff to `openapi.d.ts` is empty, the model change was non-breaking. If the diff is non-empty, fix every frontend call site the typecheck flags before merging.
3. **Don't hand-edit `openapi.d.ts`.** It will be overwritten on next regeneration. If a generated type is wrong, fix the FastAPI Pydantic model.
4. **Don't generate against prod.** The dev server is the source. Prod's `/openapi.json` may lag the merged schema during a deploy.

## Migration of existing hand-typed `.ts`

Replace existing manual type definitions in the frontend gradually:

1. Identify the endpoint a function in `lib/api/*.ts` calls.
2. Replace the manual type with the generated one:
   ```diff
   - export interface BrandOut { id: string; brand_name: string; ... }
   + import type { components } from "./openapi";
   + export type BrandOut = components["schemas"]["BrandOut"];
   ```
3. Run `npx tsc --noEmit` — fix call sites where the generated type is more precise than the manual one.

This is incremental — there's no big-bang switch. Migrate the noisiest endpoints first.
