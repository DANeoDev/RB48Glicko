"""Email delivery service supporting development mocks and production SMTP."""

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
import os
import smtplib

logger = logging.getLogger("rb48.email")

# In-memory mailbox for automated tests and development inspection
SENT_EMAILS = []


def is_smtp_configured():
    """Return True if production SMTP credentials are provided in environment."""
    return bool(os.environ.get("MAIL_SERVER") and os.environ.get("MAIL_USERNAME"))


def clear_sent_emails():
    """Clear in-memory sent emails (useful for unit testing)."""
    SENT_EMAILS.clear()


def get_last_sent_email():
    """Return the most recently dispatched email dict."""
    return SENT_EMAILS[-1] if SENT_EMAILS else None


def send_verification_email(recipient_email, username, verification_url):
    """Dispatch verification email to user."""
    subject = "Verify your RB48 Account"
    text_content = f"""Hello {username},

Thank you for registering for RB48!

Please verify your email address by visiting the following link:
{verification_url}

This link is valid for 24 hours.

Best regards,
The RB48 Team
"""

    html_content = f"""
    <div style="font-family: sans-serif; max-width: 600px; margin: auto; padding: 20px; background: #19113C; color: #bbb09d; border-radius: 8px;">
        <h2 style="color: #ffffff;">Welcome to RB48, {username}!</h2>
        <p>Please verify your email address to access player statistics and profile data.</p>
        <p style="margin: 24px 0;">
            <a href="{verification_url}" style="background: #582DA1; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">
                Verify Email Address
            </a>
        </p>
        <p style="font-size: 13px; color: #9E9A94;">Or copy and paste this link in your browser:<br>{verification_url}</p>
        <p style="font-size: 12px; color: #9E9A94; margin-top: 30px;">This link will expire in 24 hours.</p>
    </div>
    """

    email_data = {
        "recipient": recipient_email,
        "username": username,
        "subject": subject,
        "text": text_content,
        "html": html_content,
        "verification_url": verification_url,
    }
    SENT_EMAILS.append(email_data)

    if not is_smtp_configured():
        logger.info(
            "MOCK EMAIL dispatched to %s with verification link: %s",
            recipient_email,
            verification_url,
        )
        return True

    # Real SMTP Dispatch
    server_host = os.environ.get("MAIL_SERVER")
    server_port = int(os.environ.get("MAIL_PORT", 587))
    username_env = os.environ.get("MAIL_USERNAME")
    password_env = os.environ.get("MAIL_PASSWORD")
    use_tls = os.environ.get("MAIL_USE_TLS", "true").lower() in ("true", "1", "yes")
    sender = os.environ.get("MAIL_DEFAULT_SENDER", "noreply@rb48.local")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient_email

    msg.attach(MIMEText(text_content, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    try:
        server = smtplib.SMTP(server_host, server_port, timeout=10)
        if use_tls:
            server.starttls()
        if username_env and password_env:
            server.login(username_env, password_env)
        server.sendmail(sender, [recipient_email], msg.as_string())
        server.quit()
        return True
    except Exception as exc:
        logger.error("Failed to deliver verification email to %s: %s", recipient_email, exc)
        return False
