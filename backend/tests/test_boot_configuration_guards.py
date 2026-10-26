"""The app refuses to start on configuration it cannot work with.

## Why these are subprocesses

Both of these guards exist for the same reason: the failure they prevent is
**silent**. A bad CORS origin or a bad `SameSite` does not raise, does not log,
and does not redirect - it produces an app that looks healthy and is permanently
signed out. The only moment a human can still be told what is wrong is before the
process accepts a request, which means before it finishes booting.

That makes "it raises at import" the behaviour, so it has to be tested by
importing - which cannot be done in-process, because the module is already
imported by `conftest` with a valid configuration, and a cached module happily
re-raises the first result forever. A subprocess is the only way to observe it.

## What this covers

- `CORS_ORIGINS` empty or `*` — previously guarded but never tested.
- `COOKIE_SAMESITE` unrecognised, or `none` without production.

The second is the newer and more dangerous of the two: a `SameSite=None` cookie
without `Secure` is discarded by every current browser, so the deployment signs
everyone out silently. A warning would not help, because the symptom looks like
an unrelated bug in a browser that nobody is watching.
"""

import subprocess
import sys

import pytest

# A minimal environment where everything *else* is valid, so the only thing that
# can fail is the guard under test.
_BASE_ENV = {
    "APP_ENV": "production",
    "CORS_ORIGINS": "http://localhost:3000,http://localhost:3001",
    "COOKIE_SAMESITE": "lax",
    "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5435/db",
    "REDIS_URL": "redis://localhost:6382/0",
}


def _boot(env_overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    import os

    env = {
        **os.environ,
        **_BASE_ENV,
        # The test suite's own overrides would otherwise leak in and mask a guard.
        "CORS_ORIGINS": _BASE_ENV["CORS_ORIGINS"],
        **env_overrides,
    }
    return subprocess.run(
        [sys.executable, "-c", "import app.app"],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parent.parent),
    )


@pytest.mark.parametrize(
    "overrides,expected",
    [
        pytest.param({"CORS_ORIGINS": ""}, "CORS_ORIGINS cannot be empty", id="cors-empty"),
        pytest.param({"CORS_ORIGINS": "*"}, "cannot contain", id="cors-wildcard"),
        pytest.param(
            {"COOKIE_SAMESITE": "sideways"},
            "COOKIE_SAMESITE must be one of",
            id="samesite-unknown",
        ),
        pytest.param(
            {"COOKIE_SAMESITE": "none", "APP_ENV": "development"},
            "requires APP_ENV=production",
            id="samesite-none-without-https",
        ),
    ],
)
def test_boot_fails_loudly(overrides, expected):
    """A refusal at startup, with a message that names what to change.

    The message is part of the behaviour. "Refuses to start" is only useful if the
    operator is told which of the two settings to change and what to put in it
    instead; otherwise it becomes a ticket that says "the API will not boot".
    """
    result = _boot(overrides)

    assert result.returncode != 0, "the app booted on a configuration it cannot work with"
    assert expected in result.stderr, (
        f"refused to boot, but the message does not say what is wrong:\n{result.stderr[-2000:]}"
    )


def test_a_valid_cross_site_configuration_boots():
    """The fix has to actually let the deployment it exists for start.

    A guard that refuses `SameSite=None` in production too would be a guard that
    refuses the only configuration a cross-site admin app has, while looking
    exactly like a careful one. So this asserts the *positive* case: prod +
    `none` must import cleanly.
    """
    result = _boot({"COOKIE_SAMESITE": "none", "APP_ENV": "production"})

    assert result.returncode == 0, result.stderr[-2000:]


def test_the_message_for_a_bad_samesite_names_the_remedy():
    """`requires APP_ENV=production` alone leaves the operator guessing.

    They need to know what to do instead, and why the development setting differs
    from the production one - otherwise the obvious next step is to force
    production to behave like development, which is how an HTTPS deployment ends up
    with cookies that work for nobody.
    """
    result = _boot({"COOKIE_SAMESITE": "none", "APP_ENV": "development"})

    assert "COOKIE_SAMESITE" in result.stderr
    assert "lax" in result.stderr
    assert "localhost" in result.stderr


def test_the_guards_are_independent():
    """Fixing one must not satisfy the other.

    Cheap to assert and it catches the mistake where a later guard reads a
    variable the earlier one already normalised, so the second check silently
    passes on a value the first would have rejected.
    """
    result = _boot({"CORS_ORIGINS": "*", "COOKIE_SAMESITE": "sideways"})

    assert "CORS_ORIGINS" in result.stderr
    assert "COOKIE_SAMESITE" not in result.stderr, (
        "the CORS guard raised, so the SameSite guard never ran - which is correct, "
        "but means this test cannot prove the guards are independent"
    )


def test_a_good_configuration_imports():
    """The control. Without this, "it always raises" would pass everything above."""
    result = _boot({})

    assert result.returncode == 0, result.stderr[-2000:]