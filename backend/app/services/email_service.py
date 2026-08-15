import logging
import threading

logger = logging.getLogger("polymarket")


def _send_email_sync(to_email: str, subject: str, body: str):
    """Send email synchronously. Used as Celery fallback — mirrors tasks.send_email logic."""
    try:
        import smtplib
        from email.message import EmailMessage

        from app.config import settings

        if settings.smtp_host:
            msg = EmailMessage()
            msg["From"] = settings.smtp_from_email
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.set_content(body)
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_pass)
                server.send_message(msg)
            logger.info(f"[EMAIL] sent via SMTP to {to_email}: {subject}")
            return

        import resend
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
    def send_verification_code(e: str, c: str) -> None:  # noqa: N805
        EmailService.send_auth_email(e, "verify", code=c)

    def send_magic_code(e: str, c: str) -> None:  # noqa: N805
        EmailService.send_auth_email(e, "magic", code=c)

    def send_magic_url(e: str, u: str) -> None:  # noqa: N805
        EmailService.send_auth_email(e, "magic", magic_url=u)

    def send_password_reset_code(e: str, c: str) -> None:  # noqa: N805
        EmailService.send_auth_email(e, "resetpwd", code=c)
