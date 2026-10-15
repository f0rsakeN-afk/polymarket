"""Every front-end app must be allowed to make credentialed requests.

## The failure this comes from

The admin app was split out of `apps/web` onto port 3001, and `CORS_ORIGINS`
still listed one origin. Nothing broke in CI — the backend has no knowledge of
which frontends exist, so every backend test passed — and the failure only
appeared in a browser:

    Access to fetch at 'http://localhost:8000/api/v1/auth/me' from origin
    'http://localhost:3001' has been blocked by CORS policy

Which is not a cosmetic block. The apps share this API's cookies, so a missing
origin does not degrade an app, it **signs it out permanently**: the preflight
fails, `/auth/me` never returns, and the only clue is a console message in a
browser nobody was watching when the app was opened.

## Why this needs a test rather than a line in `.env.example`

The port is easy to forget precisely because SameSite ignores it. To a cookie,
`localhost:3000` and `localhost:3001` are the same site, so cookies work across
both while CORS refuses them - and the two mechanisms disagreeing about what
"origin" means is what makes this so easy to get wrong and so hard to notice.

The check below derives the required origins from the apps that actually exist,
so adding a third front end fails here rather than in someone's console.
"""

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_APPS = REPO_ROOT / "frontend" / "apps"


def _dev_port(app_dir: Path) -> int:
    """The port `next dev -p N` binds, defaulting to Next's 3000.

    Parsed from the package script rather than a declared field because that is
    where the number actually lives: a second source of truth for the port is a
    second thing to forget, which is the problem this file exists to catch.
    """
    manifest = json.loads((app_dir / "package.json").read_text())
    script = (manifest.get("scripts") or {}).get("dev", "")
    match = re.search(r"-p\s+(\d{4,5})", script)
    return int(match.group(1)) if match else 3000


def _frontend_apps() -> list[Path]:
    if not FRONTEND_APPS.is_dir():
        pytest.skip("frontend workspace not present")
    return sorted(p for p in FRONTEND_APPS.iterdir() if (p / "package.json").is_file())


@pytest.mark.parametrize("app_dir", _frontend_apps(), ids=lambda p: p.name)
def test_every_frontend_app_origin_is_allowed(app_dir: Path):
    from app.config import settings

    allowed = {o.strip() for o in settings.cors_origins.split(",") if o.strip()}
    port = _dev_port(app_dir)
    origin = f"http://localhost:{port}"

    assert origin in allowed, (
        f"{app_dir.name} runs on :{port} but CORS_ORIGINS does not allow {origin}. "
        "It cannot load a session, so it will be permanently signed out with only "
        f"a console CORS error to show for it. Allowed: {sorted(allowed)}"
    )


def test_the_admin_app_is_explicitly_allowed():
    """Named rather than derived, because this one is the regression.

    The parametrised check above would pass today if the admin app moved back
    onto 3000. This asserts the specific thing that broke.
    """
    from app.config import settings

    assert "http://localhost:3001" in settings.cors_origins


def test_wildcard_stays_rejected():
    """Credentials plus a wildcard origin is the combination that must never pass.

    `allow_credentials=True` with `*` would let any origin on the internet drive
    state-changing requests with the victim's cookies, so `app.py` raises on it.
    This pins that the default has not quietly acquired one.
    """
    from app.config import settings

    assert "*" not in settings.cors_origins.split(",")


@pytest.mark.parametrize("env_file", [".env.example"])
def test_the_example_env_lists_every_app(env_file: str):
    """`.env.example` is what a new checkout actually starts from.

    A correct default that the example file contradicts is a trap: the first
    developer to copy it lands on the broken configuration, which looks exactly
    like the default being wrong.
    """
    path = Path(__file__).resolve().parents[1] / env_file
    if not path.is_file():
        pytest.skip(f"{env_file} not present")

    line = next(
        (entry for entry in path.read_text().splitlines() if entry.startswith("CORS_ORIGINS=")),
        None,
    )
    assert line, "CORS_ORIGINS is missing from .env.example"
    listed = {o.strip() for o in line.split("=", 1)[1].split(",") if o.strip()}

    for app_dir in _frontend_apps():
        origin = f"http://localhost:{_dev_port(app_dir)}"
        assert origin in listed, (
            f".env.example omits {origin}, so copying it reproduces the bug this "
            f"file guards against"
        )