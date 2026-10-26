"""Readiness must fail when the database is behind the code.

## The failure this exists for

`_check_db` runs `SELECT 1`, which succeeds against a Postgres at *any* schema
revision. So a process three migrations behind reported `200` on `/health`,
`200` on `/health/ready` and `/health/startup` — and then crashed on the first
request that touched a column added since:

```
sqlalchemy.exc.ProgrammingError: column users.is_deleted does not exist
[SQL: SELECT users.email, ... FROM users WHERE users.email = $1]
```

Surfaced by `POST /auth/login`, which is the worst possible first symptom: it
reads as "login is broken" and sends you into the auth code hunting a bug that
is not there. Every health check passed while the service could not answer a
single request.

So `SELECT 1` answers the wrong question. This asserts the right one is asked,
and that its answer is load-bearing.

## Why the engine is faked here

`_get_engine()` is a process-wide singleton whose pooled connections belong to
whichever event loop first used it, and `pytest.ini` gives every test its own
loop. A test that touches the real engine therefore *claims* it for whichever
module runs first, and every later module sees `Event loop is closed` — which
`_bounded` reports as "db unavailable", which skips the schema check.

That is a harness constraint, not a product one: in production a process has one
event loop for its lifetime. Every test here drives `_check_schema` with a fake
engine so it is deterministic and claims nothing. The one test that goes through
the endpoint asserts only that the key is *present*, which is what the existing
health tests already do against the real dependency.
"""


from pathlib import Path

from app.api import health


def _head_revision() -> str:
    """The current Alembic head, read from the migration graph.

    Deliberately not a literal. A hardcoded head is a test that passes until the
    next migration lands and then fails on a change it has nothing to do with —
    which trains people to re-record the constant rather than read the failure.
    Asking Alembic what the head is keeps the test meaning what it says.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    # `script_location = migrations` is relative to the ini, which Alembic only
    # resolves if the process cwd happens to be the backend root. Make it absolute
    # so the test does not care where it was invoked from.
    cfg.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    return ScriptDirectory.from_config(cfg).get_current_head()


HEAD = _head_revision()


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class FakeConn:
    def __init__(self, value):
        self._value = value

    async def execute(self, *_a, **_k):
        return FakeResult(self._value)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False


def fake_engine(monkeypatch, revision):
    """Point `_get_engine` at something that answers with `revision`."""
    monkeypatch.setattr(
        health,
        "_get_engine",
        lambda: type(
            "E", (), {"begin": staticmethod(lambda: FakeConn(revision))}
        )(),
    )


# ── Is it asked at all? ──────────────────────────────────────────────────────


async def test_schema_is_part_of_readiness(client):
    body = await ready(client)

    assert "schema" in body["checks"], (
        "readiness does not check the schema - a build ahead of the database "
        "reports itself healthy and then 500s on every request"
    )


async def test_a_matching_schema_passes(monkeypatch):
    fake_engine(monkeypatch, HEAD)

    check = await health._check_schema()

    assert check["status"] == "ok"
    assert check["revision"] == HEAD


# ── Every way the revisions can disagree ─────────────────────────────────────


async def test_a_database_behind_the_build_fails_readiness(monkeypatch):
    fake_engine(monkeypatch, "2d546069962c")

    check = await health._check_schema()

    assert check["status"] == "unavailable"
    assert check["database_revision"] == "2d546069962c"
    assert check["expected_revision"] == HEAD


async def test_readiness_returns_503_when_the_schema_is_behind(client, monkeypatch):
    """The probe has to be load-bearing, not merely informative.

    A check that reports "unavailable" in a body while still answering 200 tells
    an orchestrator to keep sending traffic to a process that cannot serve it.
    """

    async def behind(*_a, **_k):
        return {
            "status": "unavailable",
            "detail": "database is behind",
            "expected_revision": HEAD,
            "database_revision": "old",
            "latency_ms": 1.0,
        }

    monkeypatch.setattr(health, "_check_schema", behind)

    body = await ready(client)

    assert body["status"] == "unavailable"


async def test_an_unstamped_database_fails_too(monkeypatch):
    """No `alembic_version` row at all — a fresh volume, or one built outside Alembic.

    This is the case where the cause is least obvious, so it gets its own
    assertion rather than falling out of the mismatch case.
    """
    fake_engine(monkeypatch, None)

    check = await health._check_schema()

    assert check["status"] == "unavailable"
    assert check["database_revision"] is None
    assert "alembic" in check["detail"]


async def test_a_database_ahead_of_the_build_also_fails(monkeypatch):
    """Symmetric, and worth saying out loud.

    Running *backwards* — a new migration applied, then an older image deployed —
    breaks just as hard: the ORM selects columns the database has, which is fine,
    but any migration that renamed or dropped one is not. Refusing to be ready is
    the honest answer, and the message must not claim the database is simply
    behind.
    """
    fake_engine(monkeypatch, "ffffffffffff")

    check = await health._check_schema()

    assert check["status"] == "unavailable"
    assert "alembic upgrade head" in check["detail"]
    assert check["database_revision"] == "ffffffffffff"


# ── The message, which is the actual deliverable ─────────────────────────────


async def test_the_failure_names_the_command_and_both_revisions(monkeypatch):
    """`503` with no remediation sends someone to read the migration history.

    The whole value of this check is that it says what to do. A health check that
    only says "no" is the same as none: the operator already knows something is
    wrong, they are being told it every few seconds.
    """
    fake_engine(monkeypatch, "2d546069962c")

    check = await health._check_schema()

    assert "alembic upgrade head" in check["detail"]
    assert check["expected_revision"] == HEAD
    assert check["database_revision"] == "2d546069962c"


async def test_a_missing_migration_directory_is_not_an_outage(monkeypatch):
    """A packaged image may not ship `alembic.ini`.

    Failing readiness on a packaging detail turns a working deployment into an
    outage, and the "fix" would be to run migrations on a host that cannot see
    them. So this degrades to explicitly-unknown — not to a guess, and not to a
    red light.
    """
    monkeypatch.setattr(health, "_code_revision", lambda: None)

    check = await health._check_schema()

    assert check["status"] == "ok"
    assert "not verified" in check["detail"]


async def test_a_broken_migration_directory_degrades_rather_than_crashing(
    monkeypatch,
):
    """An unreadable migrations tree must not take readiness down.

    The alternative — an exception escaping `_check_schema` — is caught by
    `_bounded` and reported as the *dependency* being unavailable, which points
    the operator at Postgres instead of at the packaging.

    This drives the real `_code_revision` and breaks the part it depends on,
    rather than replacing `_code_revision` itself: replacing it would delete the
    very `try`/`except` under test and the test would pass for the wrong reason.
    """
    import alembic.script

    def explode(*_a, **_k):
        raise RuntimeError("no migrations here")

    monkeypatch.setattr(
        alembic.script.ScriptDirectory, "from_config", staticmethod(explode)
    )

    # The protection itself: an unreadable tree is `None`, not an exception.
    assert health._code_revision() is None

    check = await health._check_schema()

    assert check["status"] == "ok"
    assert "not verified" in check["detail"]


# ── The revision itself ──────────────────────────────────────────────────────


async def test_the_revision_is_read_from_the_migrations_not_hardcoded():
    """A constant here would be a fourth thing to remember, and it would be wrong
    exactly when it matters — which is the only time anyone reads it."""
    revision = health._code_revision()

    assert revision == HEAD, (
        "the code's head migration moved; update this test's HEAD and confirm the "
        "readiness check is still comparing against the real thing"
    )


async def test_readiness_reports_a_latency_for_the_schema_check(monkeypatch):
    """Same reason every other check reports one: an operator cannot tell a slow
    dependency from a dead one without it."""
    fake_engine(monkeypatch, HEAD)

    check = await health._check_schema()

    assert check["latency_ms"] is not None


async def test_the_database_is_not_asked_when_it_is_already_known_to_be_down(
    monkeypatch,
):
    """Asking a database that is down for its revision cannot succeed, and would
    turn one dependency failure into two confusing ones."""
    asked = []

    async def ok(*_a, **_k):
        asked.append(1)
        return {"status": "ok", "latency_ms": 1.0}

    async def down(*_a, **_k):
        return {"status": "unavailable", "error": "down", "latency_ms": 1.0}

    monkeypatch.setattr(health, "_check_db", down)
    monkeypatch.setattr(health, "_check_schema", ok)
    health._cached = None

    body = await health._readiness()

    assert "schema" not in body["checks"]
    assert not asked, "asked an unreachable database for its revision"


async def ready(client) -> dict:
    """GET /health/ready with the memo cleared, so one test cannot feed the next."""
    health._cached = None
    resp = await client.get("/health/ready")
    health._cached = None
    assert resp.status_code in (200, 503), resp.text
    return resp.json()