# geo_common

Shared infrastructure code for the GEO platform — imported by every `geo_*` module (Cloud Run services and Cloud Run Jobs alike).

> **Not a deployable service.** `geo_common` is a pure Python source package. It is not built as a Cloud Run image; instead each module's Dockerfile copies `geo_common/` into the image and `pip install -e`s it. See `docs/roadmap.md` §3.3 Phase 2 for deployment integration details.

## What's in here

| Subpackage | Purpose |
|---|---|
| `config/` | `BaseConfig` Pydantic v2 Settings base class with unified DB / GCP / env-var conventions, plus `build_database_url()` helper. |
| `db/` | `create_asyncpg_pool()` shared connection pool creator + `@tenant_scoped` decorator (P0 multi-tenant isolation enforcement). |
| `services/` | Repository / DAL layer (`BaseRepository`, `BrandRepository`) — see Phase 4 below. |
| `schemas/` *(planned, Phase 2.x)* | Cross-module Pydantic models (Brand, Topic, Client, etc.). |
| `middleware/` *(planned)* | Shared FastAPI middleware (request_id, CORS presets). |

## Usage

In a module's `requirements.txt` (or `pyproject.toml`):

```
-e ../geo_common
```

In code:

```python
from geo_common.config import BaseConfig
from geo_common.db import create_asyncpg_pool, tenant_scoped

class Settings(BaseConfig):
    CLORO_API_KEY: str  # module-specific, inherits all DB_* / GCP_* fields

settings = Settings()
pool = await create_asyncpg_pool(settings)

@tenant_scoped
async def visibility_query(client_id: str, ...) -> dict:
    ...
```

## Status

- ✅ **Phase 2 MVP** (2026-04-25): Config base class + `@tenant_scoped` decorator + `create_asyncpg_pool()`.
- ⏳ **Phase 2.5** (planned): Migrate `geo_collector` (currently uses `databases` lib) and `geo_analyzer` (currently uses sync SQLAlchemy) to the shared asyncpg pool. Also lift `geo_analyzer` from Pydantic v1 to v2.
- 🟡 **Phase 4 in progress** (2026-04-25): `services/` package skeleton landed with `BaseRepository` + `BrandRepository` reference impl. Migration of the rest of `geo_saas` / `geo_admin` DAL into repositories is happening incrementally — only add a Repository when at least two callers would benefit. Do NOT pre-emptively extract single-use queries.

### Repository pattern

Repositories own SQL. Routers compose repositories. `@tenant_scoped` enforces multi-tenant isolation at the DAL boundary so a router that forgets a `WHERE client_id = $1` filter cannot leak data across tenants.

```python
from geo_common.services import BrandRepository

brands = BrandRepository(pool)
rows = await brands.list_for_client(client_id, include_shadow=True)
```

When adding a new Repository:
1. Subclass `BaseRepository`.
2. Decorate every tenant-scoped method with `@tenant_scoped` from `geo_common.db`.
3. Use `$1, $2, ...` parameterization — never f-strings or `.format()`.
4. Return plain `dict` rows; let the router serialize via `response_model=`.
5. Mutation methods should return the row that was written, not just `None`.

See `src/geo_common/services/brand.py` for the canonical example.

## Tests

```bash
cd geo_common
pip install -e ".[test]"
pytest
```

## Why a separate package

Before Phase 2, each of the 5 modules reimplemented its own `src/core/config.py` and `src/database.py`. Those drifted apart — `geo_collector` uses Pydantic v2 + async `databases`; `geo_analyzer` uses Pydantic v1 + sync SQLAlchemy; env-var names diverged (`DB_PASSWORD` vs `DB_PASS`). Any cross-cutting change (new field, new env, new timeout policy) had to be applied 5 times.

`geo_common` is the single source of truth for "how a GEO module talks to the database and reads its config." When a new module is spun up it inherits `BaseConfig` and gets a correct DB pool for free.
