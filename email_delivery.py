"""email_delivery.py — outgoing account mail (verification and password-reset codes).

Plain SMTP through the standard library, so any provider works (Resend, Brevo,
Gmail, SES…) and switching one is an environment change, not a code change.

Configuration (server-only, never in tracked files):

* ``SMTP_HOST`` / ``SMTP_PORT`` (default 587) / ``SMTP_USERNAME`` / ``SMTP_PASSWORD``
* ``SMTP_FROM`` — e.g. ``UZ Stock <no-reply@uzstock.uz>``
* ``SMTP_SECURITY`` — ``starttls`` (default), ``ssl`` (port 465) or ``none``
* ``EMAIL_VERIFICATION`` — ``off`` disables the code flow even when SMTP is set

Verification is on exactly when mail can be sent.  Without SMTP the site keeps
its old behaviour — requiring a code nobody can receive would lock every new
user out.
"""
from __future__ import annotations

import html
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr

logger = logging.getLogger(__name__)

CODE_TTL_MINUTES = 15


class EmailDeliveryError(RuntimeError):
    """The message could not be handed to the SMTP server."""


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def is_configured() -> bool:
    return bool(_env("SMTP_HOST") and _env("SMTP_FROM"))


def verification_enabled() -> bool:
    return is_configured() and _env("EMAIL_VERIFICATION").lower() != "off"


_TEXTS = {
    "ru": {
        "verify": ("Код подтверждения UZ Stock: {code}",
                   "Ваш код подтверждения email",
                   "Введите этот код на сайте, чтобы подтвердить адрес."),
        "reset": ("Код для сброса пароля UZ Stock: {code}",
                  "Сброс пароля",
                  "Введите этот код на сайте, чтобы задать новый пароль."),
        "ttl": "Код действует {minutes} минут.",
        "ignore": "Если вы не запрашивали код, просто проигнорируйте это письмо.",
    },
    "uz": {
        "verify": ("UZ Stock tasdiqlash kodi: {code}",
                   "Email tasdiqlash kodingiz",
                   "Manzilni tasdiqlash uchun ushbu kodni saytga kiriting."),
        "reset": ("UZ Stock parolni tiklash kodi: {code}",
                  "Parolni tiklash",
                  "Yangi parol o'rnatish uchun ushbu kodni saytga kiriting."),
        "ttl": "Kod {minutes} daqiqa amal qiladi.",
        "ignore": "Agar siz kod so'ramagan bo'lsangiz, bu xatni e'tiborsiz qoldiring.",
    },
    "en": {
        "verify": ("Your UZ Stock verification code: {code}",
                   "Your email verification code",
                   "Enter this code on the site to confirm your address."),
        "reset": ("Your UZ Stock password reset code: {code}",
                  "Password reset",
                  "Enter this code on the site to choose a new password."),
        "ttl": "The code is valid for {minutes} minutes.",
        "ignore": "If you did not request a code, you can ignore this email.",
    },
}


def render_code_email(purpose: str, code: str, language: str = "ru",
                      ttl_minutes: int = CODE_TTL_MINUTES) -> tuple[str, str, str]:
    """Return ``(subject, plain_text, html)`` for a verification or reset code."""
    texts = _TEXTS.get((language or "").lower(), _TEXTS["ru"])
    subject, heading, lead = texts["reset" if purpose == "reset" else "verify"]
    subject = subject.format(code=code)
    ttl = texts["ttl"].format(minutes=ttl_minutes)
    ignore = texts["ignore"]
    text = f"{heading}\n\n{code}\n\n{lead}\n{ttl}\n\n{ignore}\n\n— uzstock.uz\n"
    esc = html.escape
    body = f"""<!doctype html>
<html><body style="margin:0;padding:24px;background:#f4f5f7;font-family:Arial,Helvetica,sans-serif;color:#1f2328">
  <div style="max-width:440px;margin:0 auto;background:#ffffff;border-radius:10px;padding:28px">
    <h1 style="margin:0 0 12px;font-size:20px">{esc(heading)}</h1>
    <p style="margin:0 0 20px;font-size:15px;line-height:1.5">{esc(lead)}</p>
    <div style="font-size:32px;font-weight:bold;letter-spacing:8px;text-align:center;padding:16px;background:#f4f5f7;border-radius:8px">{esc(code)}</div>
    <p style="margin:20px 0 0;font-size:13px;color:#57606a">{esc(ttl)}<br>{esc(ignore)}</p>
  </div>
  <p style="text-align:center;font-size:12px;color:#8c959f">uzstock.uz</p>
</body></html>"""
    return subject, text, body


def send_email(to: str, subject: str, text: str, html_body: str | None = None) -> None:
    """Deliver one message over SMTP or raise ``EmailDeliveryError``."""
    if not is_configured():
        raise EmailDeliveryError("Email delivery is not configured")
    sender = _env("SMTP_FROM")
    name, address = parseaddr(sender)
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((name, address)) if name else address
    message["To"] = to
    message["Message-ID"] = make_msgid(domain=address.rsplit("@", 1)[-1] or None)
    message.set_content(text)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    host = _env("SMTP_HOST")
    port = int(_env("SMTP_PORT", "587") or 587)
    security = (_env("SMTP_SECURITY", "starttls") or "starttls").lower()
    timeout = float(_env("SMTP_TIMEOUT", "15") or 15)
    username, password = _env("SMTP_USERNAME"), os.getenv("SMTP_PASSWORD", "")
    context = ssl.create_default_context()
    try:
        if security == "ssl":
            client = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
        else:
            client = smtplib.SMTP(host, port, timeout=timeout)
        with client as smtp:
            if security == "starttls":
                smtp.starttls(context=context)
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        # The recipient address is personal data; the exception class is enough
        # to tell a refused connection from a rejected login.
        logger.error("email delivery failed via %s:%s: %s", host, port, type(exc).__name__)
        raise EmailDeliveryError("Could not send the email") from exc


def send_code(to: str, purpose: str, code: str, language: str = "ru") -> None:
    subject, text, body = render_code_email(purpose, code, language)
    send_email(to, subject, text, body)
