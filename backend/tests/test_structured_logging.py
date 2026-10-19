"""Logs that can actually be queried, and that do not leak an inbox.

## Two related bugs

**`extra` was discarded by both formatters.** A call site written as
`logger.info("Order filled", extra={"order_id": ...})` produced a line containing
only `"Order filled"`. So every structured field in the codebase was being thrown
away, and converting an f-string into `extra={...}` was a change that looked like
an improvement and did nothing at all — the worst kind, because it is invisible.

**Every send logged the recipient's full address at INFO.** That is a list of
everyone's email address in a log aggregator, and on a prediction market the
email is also the login identifier.

Both are asserted here because neither fails loudly. The formatter test in
particular passes whether or not the fields reach the output, unless it actually
reads the rendered line.
"""

import io
import json
import logging

import pytest

from app.app import _configure_logging


@pytest.fixture
def rendered(monkeypatch):
    """Capture what a log line actually looks like, per environment."""

    def _capture(env: str, emit) -> str:
        stream = io.StringIO()
        root = logging.getLogger()
        saved_handlers, saved_level = root.handlers[:], root.level

        # `logging.basicConfig` is a no-op when the root already has handlers, and
        # this suite runs under pytest which installs its own. Clearing first is
        # what makes `_configure_logging` actually build the formatter under test;
        # without it the capture silently reads an empty string and every
        # assertion below would pass for the wrong reason.
        root.handlers = []
        root.setLevel(logging.NOTSET)

        try:
            _configure_logging(env, "INFO")
            for handler in root.handlers:
                handler.flush()
                handler.stream = stream

            emit(logging.getLogger("probe"))
            for handler in root.handlers:
                handler.flush()
        finally:
            root.handlers = saved_handlers
            root.setLevel(saved_level)

        return stream.getvalue()

    return _capture


# ── The formatter has to render `extra` at all ───────────────────────────────


def test_production_json_carries_the_structured_fields(rendered):
    """If this fails, every `extra=` in the codebase is being discarded."""

    def emit(logger):
        logger.info("Order filled", extra={"order_id": "o1", "user_id": "u2", "amount": 10})

    line = json.loads(rendered("production", emit).strip())

    assert line["message"] == "Order filled"
    assert line["order_id"] == "o1"
    assert line["user_id"] == "u2"
    assert line["amount"] == 10
    # The standard envelope must survive alongside them.
    assert line["level"] == "INFO"
    assert line["logger"] == "probe"


def test_development_output_carries_them_too(rendered):
    """Otherwise the fields are queryable in production and invisible locally,
    which is the worst of both: you cannot reproduce what you can see."""

    def emit(logger):
        logger.info("Order filled", extra={"order_id": "o1"})

    out = rendered("development", emit)

    assert "Order filled" in out
    assert "o1" in out


def test_a_line_without_extras_is_unchanged(rendered):
    """No trailing noise, and nothing crashes when there is nothing to add."""

    def emit(logger):
        logger.info("Nothing structured here")

    assert "Nothing structured here" in rendered("development", emit)
    assert "Nothing structured here" in rendered("production", emit)


def test_the_formatted_message_is_not_duplicated_by_its_template(rendered):
    """`msg` is a reserved attribute. Emitting it would put `order %s` and
    `order 7` on the same line, and the template would look like real data to
    anything indexing the JSON."""

    def emit(logger):
        logger.info("Filled %s shares", "12", extra={"order_id": "o1"})

    line = json.loads(rendered("production", emit).strip())

    assert line["message"] == "Filled 12 shares"
    assert "msg" not in line
    assert "args" not in line


def test_unserialisable_values_do_not_break_production_logging(rendered):
    """A log line that raises is a request that 500s. `default=str` exists for
    exactly this and the test is the thing that keeps it."""

    def emit(logger):
        logger.info("Weird", extra={"thing": object()})

    line = json.loads(rendered("production", emit).strip())
    assert line["message"] == "Weird"


# ── Logs must not carry an inbox ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("trader@example.com", "t***@example.com"),
        ("a@b.io", "a***@b.io"),
        # A single-character local part is already minimal; keep it usable rather
        # than rendering `***@` for every address at a provider with short names.
        ("q@short.io", "q***@short.io"),
        # No domain: nothing to redact, and nothing to pretend about.
        ("not-an-email", "not-an-email"),
        (None, None),
    ],
)
def test_email_addresses_are_redacted(address, expected):
    from app.services.email_service import _redact_email

    assert _redact_email(address) == expected


def test_redaction_keeps_the_domain_and_drops_the_local_part():
    """The domain is what tells you whether a send is failing for one recipient
    or for a whole provider, so it is the part worth keeping."""
    from app.services.email_service import _redact_email

    out = _redact_email("verylongaddress@predictx.io")

    assert out.endswith("@predictx.io")
    assert "verylongaddress" not in out
    assert out.startswith("v")


def test_no_email_log_line_interpolates_a_raw_address():
    """A source-level guard, and deliberately so.

    `_redact_email` being correct does not stop someone writing
    `logger.info(f"sent to {to_email}")` next week. Every send used to look like
    that, and the fix is a convention rather than a type the compiler enforces.

    So: no log statement in the email service may build its message from an
    unredacted address variable. F-string messages are the risk, because they
    interpolate at the call site; a static message with `extra=` cannot.
    """
    import re
    from pathlib import Path as _Path

    source = _Path("app/services/email_service.py").read_text()

    # Only the address matters. An f-string is not itself the problem —
    # interpolating an exception into a message is fine and common — the problem
    # is an address in the message text, because `to_email` reaches the line
    # unredacted while `_redact_email` sits unused next to it.
    offenders = [
        line.strip()
        for line in source.splitlines()
        if re.search(r'logger\.(info|warning|error|debug)\(', line)
        and re.search(r'\{(to_email|email|recipient)[^}]*\}', line)
    ]

    assert not offenders, "unredacted address in a log message:\n" + "\n".join(offenders)
