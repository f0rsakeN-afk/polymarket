"""Email delivery: only retry what a retry can fix.

The failure this replaces: `send_email` retried *every* exception. With an
invalid or absent API key - a permanent configuration fault - each notification
burned max_retries with a 60s delay between attempts and raised an unpicklable
`ResendError` through Celery each time, so one misconfigured key produced a
traceback per email forever.

Three rules, in order of importance:

  1. No transport configured -> skip quietly. Not an error; a fresh checkout has
     no RESEND_API_KEY and should not generate stack traces for it.
  2. Permanent error (bad key, validation, rejected credential) -> report once,
     do not retry.
  3. Transient error (rate limit, 5xx, dropped connection) -> retry.

`_is_retryable_email_error` is a pure function over an exception, so it is
tested directly rather than through a mocked Resend client.
"""
import smtplib
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pytest
from resend.exceptions import (
    ApplicationError,
    InvalidApiKeyError,
    RateLimitError,
    ResendError,
    ValidationError,
)

from app.workers.tasks import _is_retryable_email_error as is_retryable


class TestPermanentErrorsAreNotRetried:
    """Each of these fails identically on every attempt."""

    def test_invalid_api_key(self):
        exc = InvalidApiKeyError("API key is invalid", "invalid_api_key", 401)
        assert not is_retryable(exc)

    def test_validation_error(self):
        exc = ValidationError("bad from address", "validation_error", 422)
        assert not is_retryable(exc)

    def test_missing_api_key(self):
        # An empty RESEND_API_KEY reaches Resend as a rejected credential.
        exc = ResendError(401, "invalid_api_key", "API key is invalid", "")
        assert not is_retryable(exc)

    def test_rejected_smtp_credential(self):
        # 535 is auth rejected. It never clears on its own.
        exc = smtplib.SMTPAuthenticationError(535, b"bad credentials")
        assert not is_retryable(exc)

    def test_full_mailbox(self):
        exc = smtplib.SMTPResponseException(552, b"mailbox full")
        assert not is_retryable(exc)

    def test_programming_error(self):
        assert not is_retryable(ValueError("bad argument"))


class TestTransientErrorsAreRetried:
    def test_resend_rate_limit(self):
        exc = RateLimitError("too many", "rate_limit_exceeded", 429)
        assert is_retryable(exc)

    def test_resend_server_error(self):
        exc = ApplicationError("boom", "application_error", 500)
        assert is_retryable(exc)

    def test_resend_unavailable(self):
        assert is_retryable(ResendError(503, "server_error", "down", ""))

    def test_smtp_service_unavailable(self):
        assert is_retryable(smtplib.SMTPResponseException(421, b"closing"))

    def test_smtp_busy(self):
        assert is_retryable(smtplib.SMTPResponseException(450, b"busy"))

    def test_smtp_out_of_storage(self):
        assert is_retryable(smtplib.SMTPResponseException(452, b"no storage"))

    def test_dropped_connection(self):
        assert is_retryable(ConnectionResetError())

    def test_timeout(self):
        assert is_retryable(TimeoutError())

    def test_unclassified_os_error(self):
        # A DNS or TLS blip surfaces as a plain OSError with no HTTP code.
        assert is_retryable(OSError("name resolution failed"))


class TestSendEmailBehaviour:
    """The task itself, with Resend and SMTP both stubbed out."""

    @pytest.fixture
    def task(self):
        # Imported lazily: importing the module wires up Celery.
        from app.workers.tasks import send_email

        return send_email

    @contextmanager
    def _settings(self, *, smtp_host="", resend_key=""):
        """Force the transport configuration for the duration of a test.

        `monkeypatch.setattr` on the settings instance rather than a nested
        patch.multiple: the nested form silently applied nothing, so the real
        `.env` values leaked in and the "no transport" tests exercised Resend
        instead of the skip path.
        """
        from app.config import settings

        overrides = {
            "smtp_host": smtp_host,
            "resend_api_key": resend_key,
            "smtp_port": 587,
            "smtp_user": "",
            "smtp_pass": "",
            "smtp_from_email": "noreply@example.com",
            "notifications_from_email": "noreply@example.com",
        }
        with ExitStack() as stack:
            for name, value in overrides.items():
                stack.enter_context(
                    patch.object(settings, name, value)
                )
            yield

    def test_skips_quietly_with_no_transport_configured(self, task):
        """The bug's trigger: an empty RESEND_API_KEY must not retry."""
        with self._settings(resend_key=""):
            # No Resend call, no retry, no exception.
            assert task(to_email="a@b.com", subject="s", body="b") == "skipped"

    def test_skips_when_only_smtp_host_is_blank_and_no_key(self, task):
        with self._settings(smtp_host="", resend_key=""):
            assert task(to_email="a@b.com", subject="s", body="b") == "skipped"

    def test_sends_via_resend_and_returns_sent(self, task):
        sent: dict = {}

        class FakeEmails:
            @staticmethod
            def send(payload):
                sent.update(payload)

        with self._settings(resend_key="re_valid"):
            with patch("resend.Emails", FakeEmails):
                assert task(to_email="a@b.com", subject="s", body="b") == "sent"

        assert sent["to"] == ["a@b.com"]
        assert sent["subject"] == "s"

    def test_permanent_resend_error_returns_without_retrying(self, task):
        """The regression: this used to call self.retry and raise.

        Asserted on the return value and the absence of an exception rather than
        by stubbing `retry`, because `self.retry` raises Celery's `Retry` when
        called outside a worker - so a retry attempt surfaces as an exception
        here anyway, and not seeing one is the assertion.
        """
        class FakeEmails:
            @staticmethod
            def send(_payload):
                raise InvalidApiKeyError("API key is invalid", "invalid_api_key", 401)

        with self._settings(resend_key="re_bad"):
            with patch("resend.Emails", FakeEmails):
                assert (
                    task(to_email="a@b.com", subject="s", body="b")
                    == "failed_permanently"
                )

    def test_transient_resend_error_retries(self, task):
        class FakeEmails:
            @staticmethod
            def send(_payload):
                raise RateLimitError("slow down", "rate_limit_exceeded", 429)

        with self._settings(resend_key="re_valid"):
            with patch("resend.Emails", FakeEmails):
                # Called directly rather than through a worker, Celery's
                # `Task.retry` re-raises the original exception instead of
                # requeueing. So a retry attempt is observable as the exception
                # escaping - and the contrast with the permanent case above,
                # which returns a string, is the whole behaviour under test.
                with pytest.raises(RateLimitError):
                    task(to_email="a@b.com", subject="s", body="b")