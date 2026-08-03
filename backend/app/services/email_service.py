import logging

logger = logging.getLogger("polymarket")


class EmailService:
    """
    Fire-and-forget auth email dispatch via Celery.
    All email sending goes through the `send_auth_email` task (retry + backoff handled by worker).
    """

    @staticmethod
    def send_auth_email(email: str, purpose: str, code: str | None = None, magic_url: str | None = None):
        from app.workers.tasks import send_auth_email as task

        task.delay(email=email, purpose=purpose, code=code, magic_url=magic_url)
        logger.info(f"Enqueued auth email for {email}, purpose={purpose}")

    # Convenience wrappers — keep call sites readable
    send_verification_code = lambda e, c: EmailService.send_auth_email(e, "verify", code=c)
    send_magic_code = lambda e, c: EmailService.send_auth_email(e, "magic", code=c)
    send_magic_url = lambda e, u: EmailService.send_auth_email(e, "magic", magic_url=u)
    send_password_reset_code = lambda e, c: EmailService.send_auth_email(e, "resetpwd", code=c)
