import logging
import threading

logger = logging.getLogger("polymarket")


def _send_email_sync(to_email: str, subject: str, body: str):
    """Send email synchronously via Resend API. Used by Celery worker."""
    try:
        import resend
        from app.config import settings

        if not settings.resend_api_key:
            logger.warning(f"[EMAIL MOCK] to={to_email} subject={subject}")
            return

        resend.api_key = settings.resend_api_key
        resend.Emails.send({
            "from": settings.notifications_from_email,
            "to": [to_email],
            "subject": subject,
            "text": body,
        })
        logger.info(f"[EMAIL] sent to {to_email}: {subject}")
    except Exception as exc:
        logger.error(f"[EMAIL] failed to send to {to_email}: {exc}")


class EmailService:
    """
    Fire-and-forget auth email dispatch via Celery.
    Falls back to direct sync send if Celery broker is unavailable.
    """

    @staticmethod
    def send_auth_email(
        email: str,
        purpose: str,
        code: str | None = None,
        magic_url: str | None = None,
    ):
        # Build email content
        if purpose == "verify":
            subject = f"Your PredictX verification code: {code}"
            body = f"Your verification code is: {code}\nThis code expires in 10 minutes."
        elif purpose == "magic" and magic_url:
            subject = "Your PredictX login link"
            body = f"Click this link to sign in: {magic_url}\n\nThis link expires in 15 minutes."
        elif purpose == "magic":
            subject = f"Your PredictX login code: {code}"
            body = f"Your login code is: {code}\nThis code expires in 10 minutes."
        elif purpose == "resetpwd":
            subject = f"Your PredictX password reset code: {code}"
            body = f"Your password reset code is: {code}\nThis code expires in 10 minutes."
        else:
            subject = f"Your PredictX code: {code}"
            body = f"Your code is: {code}\nThis code expires in 10 minutes."

        # Try Celery first, fall back to sync thread
        def _via_celery():
            try:
                from app.workers.tasks import send_auth_email as task
                task.delay(email=email, purpose=purpose, code=code, magic_url=magic_url)
                logger.info(f"[EMAIL] enqueued for {email}, purpose={purpose}")
            except Exception as exc:
                logger.warning(f"[EMAIL] Celery unavailable ({exc}), sending sync")
                _send_email_sync(email, subject, body)

        t = threading.Thread(target=_via_celery, daemon=True)
        t.start()

    # Convenience wrappers
    send_verification_code = lambda e, c: EmailService.send_auth_email(e, "verify", code=c)
    send_magic_code = lambda e, c: EmailService.send_auth_email(e, "magic", code=c)
    send_magic_url = lambda e, u: EmailService.send_auth_email(e, "magic", magic_url=u)
    send_password_reset_code = lambda e, c: EmailService.send_auth_email(e, "resetpwd", code=c)
