import os
import smtplib
from email.message import EmailMessage


def send_contract_email(recipients: list[str], subject: str, body: str, filename: str, pdf: bytes) -> str:
    addresses = [item.strip() for item in recipients if item.strip()]
    if not addresses:
        return ""
    host = os.environ.get("SMTP_HOST", "").strip()
    if not host:
        return "No se envió el correo porque el servidor de correo no está configurado."
    sender = os.environ.get("SMTP_FROM", "").strip() or os.environ.get("SMTP_USER", "").strip()
    if not sender:
        return "No se envió el correo porque falta el remitente."
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(addresses)
    message.set_content(body)
    message.add_attachment(pdf, maintype="application", subtype="pdf", filename=filename)
    port = int(os.environ.get("SMTP_PORT", "587") or "587")
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=20) as smtp:
                if user:
                    smtp.login(user, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=20) as smtp:
                smtp.starttls()
                if user:
                    smtp.login(user, password)
                smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        return f"No se pudo enviar el correo: {exc}"
    return "Se envió el correo a los destinatarios."
