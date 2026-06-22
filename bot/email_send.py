"""Send transactional email (login codes) over SMTP.

Sender = noreply@flagleaf.ru via Yandex Mail for Domain. Config in bot.config.settings
(smtp_host/port/user/password/from). If smtp_host is empty the feature is disabled and
send_login_code() returns False so callers can fall back to "use Telegram /weblogin".

smtplib is blocking; call from async code via asyncio.to_thread(...).
"""
import logging
import smtplib
import ssl
from email.message import EmailMessage

from bot.config import settings

logger = logging.getLogger(__name__)


def email_enabled() -> bool:
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)


def _send(to_addr: str, subject: str, body: str) -> bool:
    sender = settings.smtp_from or settings.smtp_user
    msg = EmailMessage()
    msg["From"] = f"Flagleaf <{sender}>"
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        if settings.smtp_port == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(settings.smtp_host, 465, context=ctx, timeout=20) as s:
                s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
        else:  # 587 STARTTLS
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
        return True
    except Exception as exc:
        logger.warning("SMTP send to %s failed: %s", to_addr, exc)
        return False


def send_login_code(to_addr: str, code: str) -> bool:
    """Email a 6-digit login code. Returns True on success."""
    if not email_enabled():
        return False
    body = (
        f"Ваш код для входа на сайт Flagleaf:\n\n"
        f"      {code}\n\n"
        f"Откройте ai.flagleaf.ru/app и введите код. Действует 5 минут.\n\n"
        f"Если вы не запрашивали код — просто проигнорируйте это письмо."
    )
    return _send(to_addr, "Код для входа — Flagleaf", body)
