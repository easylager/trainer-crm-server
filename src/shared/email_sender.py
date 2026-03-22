"""
Send emails via SMTP (certificate link, attachment, etc.). When SMTP is not configured, send is no-op.
"""
import logging
import smtplib
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders

from src.shared.config import Settings

logger = logging.getLogger(__name__)

CERTIFICATE_EMAIL_SUBJECT = "Ваш сертификат на занятие"
CERTIFICATE_EMAIL_BODY_HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.5;">
  <p>Здравствуйте!</p>
  <p>Вам выдан сертификат на занятие. Перейдите по ссылке, чтобы привязать сертификат к аккаунту в боте и записаться к тренеру:</p>
  <p><a href="{link}" style="display: inline-block; padding: 10px 20px; background: #2481cc; color: #fff; text-decoration: none; border-radius: 6px;">Открыть в Telegram</a></p>
  <p>Ссылка: <a href="{link}">{link}</a></p>
  <p>Если кнопка не работает, скопируйте ссылку и откройте в браузере или в приложении Telegram.</p>
</body>
</html>
"""

CERTIFICATE_PDF_EMAIL_SUBJECT = "Ваш подарочный сертификат"
CERTIFICATE_PDF_EMAIL_BODY_HTML = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.5;">
  <p>Здравствуйте!</p>
  <p>Во вложении — ваш подарочный сертификат от тренера {trainer_name}.</p>
  <p><strong>Код сертификата: {code}</strong></p>
  <p>Как воспользоваться: откройте бота или приложение тренера → выберите «У меня есть сертификат» → введите код. После привязки можно записаться на занятие.</p>
</body>
</html>
"""


def _smtp_configured() -> bool:
    s = Settings()
    return bool(
        s.smtp_host
        and s.smtp_user
        and s.smtp_password
        and s.smtp_from_email
    )


def _send_sync(
    to_email: str,
    subject: str,
    body_html: str,
    *,
    attachment_bytes: bytes | None = None,
    attachment_filename: str = "certificate.pdf",
) -> None:
    """Blocking send; raises on SMTP error. Optionally attach a PDF."""
    s = Settings()
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = s.smtp_from_email
    msg["To"] = to_email
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    if attachment_bytes:
        part = MIMEBase("application", "pdf")
        part.set_payload(attachment_bytes)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=attachment_filename)
        msg.attach(part)
    with smtplib.SMTP(s.smtp_host, s.smtp_port) as server:
        server.starttls()
        server.login(s.smtp_user, s.smtp_password)
        server.sendmail(s.smtp_from_email, [to_email], msg.as_string())


async def send_certificate_pdf_email(
    to_email: str,
    pdf_bytes: bytes,
    *,
    trainer_name: str = "Тренер",
    code: str = "",
) -> bool:
    """
    Send email with certificate PDF attached. No welcome link; body explains to use code in bot/app.
    Returns True if sent, False if SMTP not configured or send failed (logged).
    """
    if not _smtp_configured():
        logger.warning("SMTP not configured; skipping certificate PDF email")
        return False
    body = CERTIFICATE_PDF_EMAIL_BODY_HTML.format(
        trainer_name=(trainer_name or "Тренер").strip() or "Тренер",
        code=(code or "").strip() or "—",
    )
    try:
        import asyncio
        await asyncio.to_thread(
            _send_sync,
            to_email,
            CERTIFICATE_PDF_EMAIL_SUBJECT,
            body,
            attachment_bytes=pdf_bytes,
            attachment_filename="certificate.pdf",
        )
        logger.info("Certificate PDF email sent to %s", to_email)
        return True
    except Exception as e:
        logger.exception("Failed to send certificate PDF email to %s: %s", to_email, e)
        return False


async def send_certificate_link_email(to_email: str, code: str, ref_trainer_id: int | None = None) -> bool:
    """
    Send email with bot link to activate certificate. Link: t.me/<client_bot_username>?start=cert_<code>
    Optional ref: start=cert_<code>_ref_<trainer_id> for preselected trainer (handled in bot).
    Returns True if sent, False if SMTP/bot username not configured or send failed (logged).
    """
    s = Settings()
    if not s.client_bot_username:
        logger.warning("client_bot_username not set; skipping certificate email")
        return False
    if not _smtp_configured():
        logger.warning("SMTP not configured; skipping certificate email")
        return False
    start_param = f"cert_{code}"
    if ref_trainer_id is not None:
        start_param += f"_ref_{ref_trainer_id}"
    link = f"https://t.me/{s.client_bot_username.lstrip('@')}?start={start_param}"
    body = CERTIFICATE_EMAIL_BODY_HTML_TEMPLATE.format(link=link)
    try:
        import asyncio
        await asyncio.to_thread(_send_sync, to_email, CERTIFICATE_EMAIL_SUBJECT, body)
        logger.info("Certificate link email sent to %s", to_email)
        return True
    except Exception as e:
        logger.exception("Failed to send certificate email to %s: %s", to_email, e)
        return False
