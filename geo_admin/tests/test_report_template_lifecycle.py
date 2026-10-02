from uuid import UUID

import pytest

from geo_common.services import WorkspaceLifecycleMissing
from routers import report_templates


CLIENT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class Tx:
    async def __aenter__(self): return self
    async def __aexit__(self, *args): return False


class Conn:
    def __init__(self, exists=True):
        self.exists = exists
        self.events = []

    def transaction(self): return Tx()

    async def fetchval(self, sql, *args):
        if "pg_try_advisory_xact_lock_shared" in sql:
            self.events.append(("lock", args[0]))
            return True
        if "SELECT EXISTS" in sql:
            self.events.append(("exists", args[0]))
            return self.exists
        raise AssertionError(sql)

    async def fetchrow(self, sql, *args):
        assert "INSERT INTO geo_report_templates" in sql
        self.events.append(("insert", str(args[5])))
        return {"id": UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"), "name": args[0]}

    async def execute(self, sql, *args):
        assert "DELETE FROM geo_report_templates" in sql
        self.events.append(("delete", str(args[0])))
        return "DELETE 1"


class Acquire:
    def __init__(self, conn): self.conn = conn
    async def __aenter__(self): return self.conn
    async def __aexit__(self, *args): return False


class Pool:
    def __init__(self, conn): self.conn = conn
    def acquire(self): return Acquire(self.conn)


@pytest.mark.anyio
async def test_client_template_create_locks_checks_and_inserts_on_same_connection(monkeypatch):
    conn = Conn()
    monkeypatch.setattr(report_templates.database, "_pool", Pool(conn))

    result = await report_templates.create_template(
        report_templates.TemplateCreate(name="Tenant report", client_id=CLIENT_A)
    )

    assert result.name == "Tenant report"
    assert conn.events == [
        ("lock", f"workspace-lifecycle:{CLIENT_A}"),
        ("exists", CLIENT_A),
        ("insert", CLIENT_A),
    ]


@pytest.mark.anyio
async def test_client_template_create_rejects_missing_workspace_before_insert(monkeypatch):
    conn = Conn(exists=False)
    monkeypatch.setattr(report_templates.database, "_pool", Pool(conn))

    with pytest.raises(WorkspaceLifecycleMissing):
        await report_templates.create_template(
            report_templates.TemplateCreate(name="Late", client_id=CLIENT_A)
        )

    assert all(event[0] != "insert" for event in conn.events)


@pytest.mark.anyio
async def test_tenant_template_delete_uses_workspace_guard(monkeypatch):
    template_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    conn = Conn()

    async def fetch_one(*args, **kwargs):
        return {"is_builtin": False, "client_id": CLIENT_A}

    monkeypatch.setattr(report_templates.database, "_pool", Pool(conn))
    monkeypatch.setattr(report_templates.database, "fetch_one", fetch_one)

    await report_templates.delete_template(template_id)

    assert conn.events == [
        ("lock", f"workspace-lifecycle:{CLIENT_A}"),
        ("exists", CLIENT_A),
        ("delete", str(template_id)),
    ]


@pytest.mark.anyio
async def test_global_non_builtin_template_delete_uses_direct_transaction(monkeypatch):
    template_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    conn = Conn()

    async def fetch_one(*args, **kwargs):
        return {"is_builtin": False, "client_id": None}

    monkeypatch.setattr(report_templates.database, "_pool", Pool(conn))
    monkeypatch.setattr(report_templates.database, "fetch_one", fetch_one)

    await report_templates.delete_template(template_id)

    assert conn.events == [("delete", str(template_id))]


@pytest.mark.anyio
async def test_global_builtin_template_delete_remains_forbidden(monkeypatch):
    async def fetch_one(*args, **kwargs):
        return {"is_builtin": True, "client_id": None}

    monkeypatch.setattr(report_templates.database, "fetch_one", fetch_one)

    with pytest.raises(report_templates.HTTPException) as exc:
        await report_templates.delete_template(
            UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        )

    assert exc.value.status_code == 403
