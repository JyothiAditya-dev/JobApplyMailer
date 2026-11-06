import os
import smtplib
import time
import base64
import mimetypes
from pathlib import Path
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from googleapiclient.discovery import build

from app.database import (
    get_all_settings,
    get_campaign,
    get_resume,
    update_campaign_status,
    update_campaign_recipient_send_status,
    log_email_send
)
from app.google_auth import get_google_credentials, is_google_connected

BASE_DIR = Path(__file__).resolve().parent.parent
RESUME_DIR = BASE_DIR / "uploads" / "resumes"


def create_mime_message(
    sender_email: str,
    sender_name: str,
    to_email: str,
    subject: str,
    body_text: str,
    resume_path: str = None,
    resume_filename: str = None
) -> MIMEMultipart:
    """
    Constructs a MIMEMultipart email message with optional resume attachment.
    """
    msg = MIMEMultipart()
    from_header = f'"{sender_name}" <{sender_email}>' if sender_name else sender_email
    msg["From"] = from_header
    msg["To"] = to_email
    msg["Subject"] = subject

    # Plain text body
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    # Resume Attachment
    if resume_path and Path(resume_path).is_file():
        file_path = Path(resume_path)
        content_type, _ = mimetypes.guess_type(str(file_path))
        if content_type is None:
            content_type = "application/octet-stream"
        main_type, sub_type = content_type.split("/", 1)

        try:
            with open(file_path, "rb") as f:
                part = MIMEBase(main_type, sub_type)
                part.set_payload(f.read())
            encoders.encode_base64(part)
            filename = resume_filename or file_path.name
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{filename}"'
            )
            msg.attach(part)
        except Exception as e:
            print(f"Warning attaching resume: {e}")

    return msg


def send_email_via_gmail_api(to_email: str, subject: str, body_text: str, resume_path=None, resume_filename=None):
    """
    Sends an email using the official Google Gmail REST API over HTTPS (Port 443).
    Bypasses ISP port 587/25 blocks completely.
    Returns (success: bool, error: str | None).
    """
    creds = get_google_credentials()
    if not creds:
        return False, "Google account is not connected. Please click 'Connect with Google'."

    try:
        service = build("gmail", "v1", credentials=creds)

        settings = get_all_settings()
        sender_email = settings.get("sender_email", "").strip() or "me"
        sender_name = settings.get("sender_name", "").strip() or "Job Applicant"

        msg = create_mime_message(
            sender_email=sender_email,
            sender_name=sender_name,
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            resume_path=resume_path,
            resume_filename=resume_filename
        )

        raw_bytes = msg.as_bytes()
        raw_b64 = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")

        body_payload = {"raw": raw_b64}
        sent_resp = service.users().messages().send(userId="me", body=body_payload).execute()

        return True, None
    except Exception as e:
        return False, str(e)


def send_single_email_smtp(
    host,
    port,
    sender_email,
    sender_name,
    password,
    to_email,
    subject,
    body_text,
    resume_path=None,
    resume_filename=None,
    use_ssl=False
):
    """
    Fallback: Sends email via traditional SMTP.
    """
    msg = create_mime_message(
        sender_email=sender_email,
        sender_name=sender_name,
        to_email=to_email,
        subject=subject,
        body_text=body_text,
        resume_path=resume_path,
        resume_filename=resume_filename
    )

    try:
        port = int(port)
        if use_ssl or port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
            server.ehlo()
            server.starttls()
            server.ehlo()

        server.login(sender_email, password)
        server.send_message(msg)
        server.quit()
        return True, None
    except Exception as e:
        return False, str(e)


def send_email_smart(to_email: str, subject: str, body_text: str, resume_path=None, resume_filename=None):
    """
    Smart delivery dispatcher:
    1. If Google OAuth is connected -> Uses official Gmail API (HTTPS/443).
    2. Else -> Uses SMTP fallback.
    """
    if is_google_connected():
        return send_email_via_gmail_api(to_email, subject, body_text, resume_path, resume_filename)

    # SMTP fallback
    settings = get_all_settings()
    host = settings.get("smtp_host", "smtp.gmail.com")
    port = settings.get("smtp_port", "587")
    sender_email = settings.get("sender_email", "").strip()
    sender_name = settings.get("sender_name", "").strip()
    password = settings.get("smtp_password", "").strip()
    use_ssl = str(settings.get("smtp_use_ssl", "")).lower() in ("true", "1")

    if not sender_email or not password:
        return False, "Neither Google OAuth nor SMTP credentials are configured."

    return send_single_email_smtp(
        host=host,
        port=port,
        sender_email=sender_email,
        sender_name=sender_name,
        password=password,
        to_email=to_email,
        subject=subject,
        body_text=body_text,
        resume_path=resume_path,
        resume_filename=resume_filename,
        use_ssl=use_ssl
    )


def test_smtp_connection(host, port, user, password, use_ssl=False):
    """
    SMTP diagnostics.
    """
    if not host or not user or not password:
        return False, "Host, user email, and password / app password are required."

    try:
        port = int(port)
        if use_ssl or port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            server.ehlo()
            server.starttls()
            server.ehlo()

        server.login(user, password)
        server.quit()
        return True, "SMTP connection and authentication successful!"
    except smtplib.SMTPAuthenticationError as e:
        return False, f"Authentication failed: Check your Gmail App Password. ({e})"
    except Exception as e:
        return False, f"Connection failed: {str(e)}"


def run_campaign_send(campaign_id: int):
    """
    Background worker that sends approved emails in a campaign batch.
    Includes rate-limiting delay between sends and full database logging.
    """
    settings = get_all_settings()
    sender_name = settings.get("sender_name", "").strip()

    try:
        delay = float(settings.get("delay_seconds", "3"))
    except ValueError:
        delay = 3.0

    if not is_google_connected() and not (settings.get("sender_email") and settings.get("smtp_password")):
        update_campaign_status(campaign_id, "paused")
        return {"error": "Gmail is not connected. Connect with Google in Settings."}

    campaign = get_campaign(campaign_id)
    if not campaign:
        return {"error": "Campaign not found."}

    # Mark campaign as sending
    update_campaign_status(campaign_id, "sending")

    # Get resume file if available
    resume = get_resume()
    resume_path = None
    resume_filename = None
    if resume:
        stored = RESUME_DIR / resume["stored_filename"]
        if stored.is_file():
            resume_path = str(stored)
            resume_filename = resume["original_filename"]

    # Filter recipients: only approved and not yet sent
    recipients = [
        r for r in campaign["recipients"]
        if r["review_status"] == "approved" and r["send_status"] != "sent"
    ]

    sent_count = 0
    failed_count = 0

    for r in recipients:
        # Check if campaign was paused or cancelled mid-send
        fresh = get_campaign(campaign_id)
        if fresh and fresh["status"] in ("paused", "cancelled"):
            break

        # Personalize subject & body
        replacements = {
            "{{recruiter_name}}": r.get("recipient_name") or "Hiring Team",
            "{{sender_name}}": sender_name or "Your Name",
            "{{job_role}}": "Software Engineer",
            "{{company_name}}": "your esteemed organization"
        }

        subject = campaign["template_subject"]
        body = campaign["template_body"]

        for k, v in replacements.items():
            subject = subject.replace(k, v)
            body = body.replace(k, v)

        # Send email via smart dispatcher (Gmail API over HTTPS or SMTP)
        success, error_msg = send_email_smart(
            to_email=r["recipient_email"],
            subject=subject,
            body_text=body,
            resume_path=resume_path,
            resume_filename=resume_filename
        )

        status_str = "sent" if success else "failed"
        update_campaign_recipient_send_status(r["id"], status_str, error_msg)
        log_email_send(
            campaign_id=campaign_id,
            recipient_id=r["id"],
            recipient_email=r["recipient_email"],
            subject=subject,
            status=status_str,
            error_message=error_msg
        )

        if success:
            sent_count += 1
        else:
            failed_count += 1

        # Rate-limiting delay
        time.sleep(delay)

    # If all approved were processed, mark as completed
    fresh = get_campaign(campaign_id)
    if fresh and fresh["status"] == "sending":
        update_campaign_status(campaign_id, "completed")

    return {
        "campaign_id": campaign_id,
        "processed": len(recipients),
        "sent": sent_count,
        "failed": failed_count
    }
