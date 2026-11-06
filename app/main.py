import csv
import io
import re
import uuid
import sqlite3
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import FastAPI, Request, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, Response, RedirectResponse
from fastapi.templating import Jinja2Templates
from openpyxl import load_workbook
from pydantic import BaseModel, Field

from app.database import (
    initialize_database,
    save_contacts,
    get_all_contacts,
    get_contact_count,
    delete_contact,
    save_resume,
    get_resume,
    delete_resume,
    create_email_template,
    get_all_email_templates,
    get_email_template,
    update_email_template,
    delete_email_template,
    get_email_template_count,
    create_campaign,
    get_all_campaigns,
    get_campaign,
    update_campaign_status,
    update_campaign_recipient_status,
    delete_campaign,
    get_campaign_count,
    get_all_settings,
    set_setting,
    get_setting,
    get_email_logs,
    get_total_sent_count
)
from app.google_auth import (
    CLIENT_SECRET_FILE,
    is_google_connected,
    get_authenticated_user_info,
    get_authorization_url,
    exchange_code_for_token,
    disconnect_google
)
from app.mailer import (
    test_smtp_connection,
    send_single_email_smtp,
    send_email_via_gmail_api,
    send_email_smart,
    run_campaign_send
)

# --------------------------------------------------
# APPLICATION CONFIGURATION
# --------------------------------------------------

app = FastAPI(
    title="JobApply Mailer",
    description="Smart Email Automation for Job Seekers with Google OAuth & Gmail API",
    version="2.2.0",
)

templates = Jinja2Templates(directory="app/templates")

MAX_FILE_SIZE = 5 * 1024 * 1024
MAX_ROWS = 5000

BASE_DIR = Path(__file__).resolve().parent.parent
RESUME_DIR = BASE_DIR / "uploads" / "resumes"
RESUME_DIR.mkdir(parents=True, exist_ok=True)

EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$"
)

initialize_database()


# --------------------------------------------------
# REQUEST MODELS
# --------------------------------------------------

class EmailTemplateInput(BaseModel):
    template_name: str = Field(min_length=1, max_length=100)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10000)


class CampaignCreateInput(BaseModel):
    campaign_name: str = Field(min_length=1, max_length=120)
    template_id: int = Field(gt=0)
    contact_ids: List[int] = Field(min_length=1, max_length=5000)


class CampaignStatusInput(BaseModel):
    status: Literal["draft", "review", "sending", "completed", "paused", "cancelled"]


class RecipientReviewInput(BaseModel):
    review_status: Literal["pending", "approved", "suppressed"]


class SettingsInput(BaseModel):
    sender_name: str = Field(min_length=1, max_length=100)
    sender_email: str = Field(min_length=3, max_length=150)
    smtp_host: str = Field(default="smtp.gmail.com")
    smtp_port: str = Field(default="587")
    smtp_use_ssl: bool = Field(default=False)
    smtp_password: Optional[str] = Field(default=None)
    delay_seconds: str = Field(default="3")
    daily_limit: str = Field(default="50")


class TestEmailInput(BaseModel):
    test_email: Optional[str] = None


# --------------------------------------------------
# DASHBOARD AND HEALTH
# --------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    settings = get_all_settings()
    google_connected = is_google_connected()
    google_user = get_authenticated_user_info() if google_connected else None

    connected_email = google_user["email"] if google_user else settings.get("sender_email", "")
    connected_name = (google_user["name"] if google_user else "") or settings.get("sender_name", "Job Seeker")
    is_connected = google_connected or bool(settings.get("sender_email") and settings.get("smtp_password"))

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "title": "JobApply Mailer",
            "total_contacts": get_contact_count(),
            "resume": get_resume(),
            "total_campaigns": get_campaign_count(),
            "total_templates": get_email_template_count(),
            "total_sent": get_total_sent_count(),
            "settings": settings,
            "is_connected": is_connected,
            "is_google_connected": google_connected,
            "sender_email": connected_email,
            "sender_name": connected_name,
        },
    )


@app.get("/health")
async def health():
    return {
        "status": "running",
        "application": "JobApply Mailer",
        "version": "2.2.0",
        "google_oauth": is_google_connected()
    }


@app.get("/api/stats")
async def get_stats():
    settings = get_all_settings()
    google_connected = is_google_connected()
    google_user = get_authenticated_user_info() if google_connected else None

    connected_email = google_user["email"] if google_user else settings.get("sender_email", "")
    connected_name = (google_user["name"] if google_user else "") or settings.get("sender_name", "Job Seeker")
    is_connected = google_connected or bool(settings.get("sender_email") and settings.get("smtp_password"))

    return {
        "total_contacts": get_contact_count(),
        "total_sent": get_total_sent_count(),
        "total_campaigns": get_campaign_count(),
        "total_templates": get_email_template_count(),
        "is_connected": is_connected,
        "is_google_connected": google_connected,
        "auth_method": "Google OAuth 2.0 (Gmail API)" if google_connected else ("SMTP" if is_connected else "None"),
        "sender_email": connected_email,
        "sender_name": connected_name
    }


# --------------------------------------------------
# GOOGLE OAUTH 2.0 (OFFICIAL GMAIL API)
# --------------------------------------------------

def get_oauth_redirect_uri(request: Request) -> str:
    # 1. Custom app URL from environment variable (e.g. Render / Railway / Production domain)
    import os
    env_url = os.environ.get("APP_URL") or os.environ.get("RENDER_EXTERNAL_URL")
    if env_url:
        return f"{env_url.rstrip('/')}/api/auth/google/callback"

    # 2. Localhost development
    host = request.url.hostname or "localhost"
    if host in ("127.0.0.1", "localhost"):
        port = request.url.port or 8000
        return f"http://localhost:{port}/api/auth/google/callback"

    # 3. Dynamic online host
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme or "https"
    port_part = f":{request.url.port}" if request.url.port and request.url.port not in (80, 443) else ""
    return f"{scheme}://{host}{port_part}/api/auth/google/callback"


@app.get("/api/auth/google/status")
async def get_google_auth_status():
    connected = is_google_connected()
    user = get_authenticated_user_info() if connected else None
    return {
        "connected": connected,
        "user": user,
        "client_secret_exists": CLIENT_SECRET_FILE.is_file()
    }


@app.get("/api/auth/google/login")
async def google_login_redirect(request: Request):
    """
    Redirects the user directly to Google's official authorization screen.
    """
    redirect_uri = get_oauth_redirect_uri(request)
    try:
        auth_url = get_authorization_url(redirect_uri)
        return RedirectResponse(url=auth_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/auth/google/callback")
async def google_auth_callback(request: Request, code: Optional[str] = None, error: Optional[str] = None):
    """
    Handles redirect back from Google authorization screen.
    Exchanges code for tokens, saves credentials, and redirects back to dashboard.
    """
    if error:
        return RedirectResponse(url=f"/#settings?google_error={error}")

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code from Google.")

    redirect_uri = get_oauth_redirect_uri(request)

    try:
        user_info = exchange_code_for_token(code=code, redirect_uri=redirect_uri)
        email = user_info.get("email", "")
        return RedirectResponse(url=f"/#settings?google_success=1&email={email}")
    except Exception as e:
        return RedirectResponse(url=f"/#settings?google_error={str(e)}")


@app.post("/api/auth/google/disconnect")
async def disconnect_google_account():
    disconnect_google()
    return {"message": "Google account disconnected successfully."}


@app.post("/api/auth/google/test")
async def test_google_connection():
    if not is_google_connected():
        raise HTTPException(
            status_code=400,
            detail="Google account is not connected yet. Click 'Connect Google Account' first."
        )

    user = get_authenticated_user_info()
    if not user or not user.get("email"):
        raise HTTPException(status_code=400, detail="Could not read Google account details.")

    test_sub = "JobApply Mailer - Google Connection Verified! 🎉"
    test_body = (
        f"Hello {user.get('name') or 'Job Seeker'},\n\n"
        f"Your Gmail account ({user.get('email')}) is successfully connected to JobApply Mailer via Google OAuth 2.0!\n\n"
        f"All application emails are sent directly through the official Gmail API over HTTPS (Port 443), completely bypassing ISP port 587/25 limits.\n\n"
        f"Happy job hunting!\n"
        f"— JobApply Mailer"
    )

    sent, err = send_email_via_gmail_api(
        to_email=user["email"],
        subject=test_sub,
        body_text=test_body
    )

    if not sent:
        raise HTTPException(
            status_code=400,
            detail=f"Google authenticated, but failed to deliver test email: {err}"
        )

    return {
        "success": True,
        "message": f"Connection verified! A test email was delivered to {user['email']}."
    }


# --------------------------------------------------
# CONTACT MANAGEMENT
# --------------------------------------------------

@app.get("/api/contacts")
async def list_contacts():
    contacts = get_all_contacts()
    return {"total_contacts": len(contacts), "contacts": contacts}


@app.get("/api/contacts/search")
async def search_contacts(q: str = ""):
    contacts = get_all_contacts(q.strip())
    return {"total_contacts": len(contacts), "contacts": contacts}


@app.delete("/api/contacts/{contact_id}")
async def remove_contact(contact_id: int):
    deleted = delete_contact(contact_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Contact not found.")
    return {
        "message": "Contact deleted successfully.",
        "total_contacts": get_contact_count(),
    }


@app.post("/api/contacts/upload")
async def upload_contacts(file: UploadFile = File(...)):
    filename = (file.filename or "").lower()

    if not filename.endswith((".csv", ".xlsx")):
        raise HTTPException(
            status_code=400,
            detail="Only CSV and XLSX files are supported.",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File size must be 5 MB or less.")

    try:
        if filename.endswith(".csv"):
            rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
        else:
            workbook = load_workbook(
                io.BytesIO(content), read_only=True, data_only=True
            )
            rows = list(workbook.active.iter_rows(values_only=True))
            workbook.close()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Could not read this file. Check the file format.",
        )

    if len(rows) < 2:
        raise HTTPException(
            status_code=400,
            detail="File needs a header and at least one contact.",
        )

    headers = [
        str(value).strip().lower() if value is not None else ""
        for value in rows[0]
    ]

    email_index = next(
        (
            i for i, header in enumerate(headers)
            if header in ("email", "email address", "e-mail", "mail")
        ),
        None,
    )

    if email_index is None:
        raise HTTPException(status_code=400, detail="Add a column named Email.")

    name_index = next(
        (
            i for i, header in enumerate(headers)
            if header in ("name", "full name", "contact name", "recruiter", "recruiter name")
        ),
        None,
    )

    contacts = []
    seen = set()
    invalid = 0
    duplicates = 0

    for row in rows[1:MAX_ROWS + 1]:
        if email_index >= len(row) or row[email_index] is None:
            continue

        email = str(row[email_index]).strip().lower()
        if not email:
            continue

        if not EMAIL_PATTERN.fullmatch(email):
            invalid += 1
            continue

        if email in seen:
            duplicates += 1
            continue

        seen.add(email)
        name = ""
        if name_index is not None and name_index < len(row):
            name = str(row[name_index] or "").strip()

        contacts.append({"name": name, "email": email})

    if not contacts:
        raise HTTPException(
            status_code=400,
            detail="No valid contacts found in the file.",
        )

    saved_count, already_saved = save_contacts(contacts)

    return {
        "message": "Contacts processed and saved successfully.",
        "total_valid": len(contacts),
        "saved_count": saved_count,
        "already_saved": already_saved,
        "invalid": invalid,
        "duplicates": duplicates,
        "total_contacts_in_database": get_contact_count(),
    }


@app.get("/api/contacts/sample-template")
async def sample_contacts_template():
    csv_content = "Name,Email\nRahul Sharma,rahul.sharma@example.com\nSarah Jenkins,sjenkins@techrecruiting.org\nHiring Team,careers@innovatetech.io\n"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sample_contacts.csv"}
    )


# --------------------------------------------------
# RESUME MANAGEMENT
# --------------------------------------------------

@app.get("/api/resume")
async def resume_status():
    resume = get_resume()
    if not resume:
        return {"uploaded": False, "message": "No resume uploaded yet."}

    return {
        "uploaded": True,
        "resume": {
            "id": resume["id"],
            "filename": resume["original_filename"],
            "file_type": resume["file_type"],
            "file_size": resume["file_size"],
            "uploaded_at": resume["uploaded_at"],
        },
    }


@app.post("/api/resume/upload")
async def upload_resume(file: UploadFile = File(...)):
    original_filename = Path(file.filename or "").name
    extension = Path(original_filename).suffix.lower()

    if extension not in (".pdf", ".docx"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF and DOCX resumes are supported.",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded resume is empty.")

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Resume size must be 5 MB or less.")

    if extension == ".pdf" and not content.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=400,
            detail="The file does not appear to be a valid PDF.",
        )

    if extension == ".docx" and not content.startswith(b"PK"):
        raise HTTPException(
            status_code=400,
            detail="The file does not appear to be a valid DOCX document.",
        )

    stored_filename = f"{uuid.uuid4().hex}{extension}"
    file_path = RESUME_DIR / stored_filename
    old_resume = get_resume()

    try:
        file_path.write_bytes(content)
        save_resume(
            original_filename=original_filename,
            stored_filename=stored_filename,
            file_type=extension.lstrip(".").upper(),
            file_size=len(content),
        )
    except Exception:
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500,
            detail="Could not save the resume.",
        )

    if old_resume:
        old_file = RESUME_DIR / old_resume["stored_filename"]
        old_file.unlink(missing_ok=True)

    return {
        "message": "Resume uploaded successfully.",
        "resume": {
            "filename": original_filename,
            "file_type": extension.lstrip(".").upper(),
            "file_size": len(content),
        },
    }


@app.get("/api/resume/download")
async def download_resume():
    resume = get_resume()
    if not resume:
        raise HTTPException(status_code=404, detail="No resume has been uploaded.")

    file_path = RESUME_DIR / resume["stored_filename"]
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Resume file is missing from storage.")

    media_type = (
        "application/pdf"
        if resume["file_type"] == "PDF"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=resume["original_filename"],
    )


@app.delete("/api/resume")
async def remove_resume():
    resume = get_resume()
    if not resume:
        raise HTTPException(status_code=404, detail="No resume has been uploaded.")

    deleted = delete_resume()
    if not deleted:
        raise HTTPException(
            status_code=500,
            detail="Could not delete resume information.",
        )

    (RESUME_DIR / resume["stored_filename"]).unlink(missing_ok=True)
    return {"message": "Resume deleted successfully."}


# --------------------------------------------------
# EMAIL TEMPLATE MANAGEMENT
# --------------------------------------------------

@app.get("/api/email-templates")
async def list_email_templates(search: str = ""):
    templates_list = get_all_email_templates(search.strip())
    return {
        "total_templates": len(templates_list),
        "templates": templates_list,
    }


@app.get("/api/email-templates/{template_id}")
async def read_email_template(template_id: int):
    template = get_email_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Email template not found.")
    return template


@app.post("/api/email-templates")
async def add_email_template(data: EmailTemplateInput):
    template_id = create_email_template(
        data.template_name.strip(),
        data.subject.strip(),
        data.body.strip(),
    )
    return {
        "message": "Email template created successfully.",
        "template_id": template_id,
        "total_templates": get_email_template_count(),
    }


@app.put("/api/email-templates/{template_id}")
async def edit_email_template(template_id: int, data: EmailTemplateInput):
    if not get_email_template(template_id):
        raise HTTPException(status_code=404, detail="Email template not found.")

    updated = update_email_template(
        template_id,
        data.template_name.strip(),
        data.subject.strip(),
        data.body.strip(),
    )
    if not updated:
        raise HTTPException(
            status_code=500,
            detail="Could not update email template.",
        )
    return {
        "message": "Email template updated successfully.",
        "template_id": template_id,
    }


@app.delete("/api/email-templates/{template_id}")
async def remove_email_template(template_id: int):
    try:
        deleted = delete_email_template(template_id)
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="This template is used by a campaign and cannot be deleted.",
        )

    if not deleted:
        raise HTTPException(status_code=404, detail="Email template not found.")

    return {
        "message": "Email template deleted successfully.",
        "total_templates": get_email_template_count(),
    }


@app.post("/api/email-templates/{template_id}/preview")
async def preview_email_template(
    template_id: int,
    recruiter_name: str = "Hiring Team",
    sender_name: str = "Your Name",
    job_role: str = "Python Developer",
    company_name: str = "Company",
):
    template = get_email_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Email template not found.")

    replacements = {
        "{{recruiter_name}}": recruiter_name,
        "{{sender_name}}": sender_name,
        "{{job_role}}": job_role,
        "{{company_name}}": company_name,
    }

    subject = template["subject"]
    body = template["body"]
    for placeholder, value in replacements.items():
        subject = subject.replace(placeholder, value)
        body = body.replace(placeholder, value)

    return {"template_id": template_id, "subject": subject, "body": body}


# --------------------------------------------------
# CAMPAIGN MANAGEMENT
# --------------------------------------------------

@app.get("/api/campaigns")
async def list_campaigns():
    campaigns = get_all_campaigns()
    return {
        "total_campaigns": len(campaigns),
        "campaigns": campaigns,
    }


@app.get("/api/campaigns/count")
async def campaign_count():
    return {"total_campaigns": get_campaign_count()}


@app.get("/api/campaigns/{campaign_id}")
async def read_campaign(campaign_id: int):
    campaign = get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    return campaign


@app.post("/api/campaigns")
async def add_campaign(data: CampaignCreateInput):
    try:
        campaign_id = create_campaign(
            data.campaign_name,
            data.template_id,
            data.contact_ids,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    return {
        "message": "Draft campaign created. No emails have been sent.",
        "campaign_id": campaign_id,
        "status": "draft",
    }


@app.patch("/api/campaigns/{campaign_id}/status")
async def change_campaign_status(campaign_id: int, data: CampaignStatusInput):
    if not get_campaign(campaign_id):
        raise HTTPException(status_code=404, detail="Campaign not found.")

    try:
        update_campaign_status(campaign_id, data.status)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    return {
        "message": "Campaign status updated.",
        "campaign_id": campaign_id,
        "status": data.status,
    }


@app.patch("/api/campaigns/recipients/{recipient_id}/review")
async def review_campaign_recipient(
    recipient_id: int,
    data: RecipientReviewInput,
):
    try:
        updated = update_campaign_recipient_status(
            recipient_id,
            data.review_status,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    if not updated:
        raise HTTPException(status_code=404, detail="Campaign recipient not found.")

    return {
        "message": "Recipient review status updated.",
        "recipient_id": recipient_id,
        "review_status": data.review_status,
    }


@app.post("/api/campaigns/{campaign_id}/preview")
async def preview_campaign(campaign_id: int):
    campaign = get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    settings = get_all_settings()
    google_user = get_authenticated_user_info() if is_google_connected() else None
    sender_name = (google_user["name"] if google_user else "") or settings.get("sender_name") or "Your Name"

    previews = []
    for recipient in campaign["recipients"]:
        replacements = {
            "{{recruiter_name}}": recipient.get("recipient_name") or "Hiring Team",
            "{{sender_name}}": sender_name,
            "{{job_role}}": "Software Engineer",
            "{{company_name}}": "your company",
        }

        subject = campaign["template_subject"]
        body = campaign["template_body"]

        for placeholder, value in replacements.items():
            subject = subject.replace(placeholder, value)
            body = body.replace(placeholder, value)

        previews.append({
            "recipient_id": recipient["id"],
            "recipient_name": recipient["recipient_name"],
            "recipient_email": recipient["recipient_email"],
            "subject": subject,
            "body": body,
            "review_status": recipient["review_status"],
            "send_status": recipient.get("send_status", "unattempted"),
        })

    return {
        "campaign_id": campaign_id,
        "campaign_name": campaign["campaign_name"],
        "status": campaign["status"],
        "total_recipients": len(previews),
        "previews": previews,
    }


@app.delete("/api/campaigns/{campaign_id}")
async def remove_campaign(campaign_id: int):
    try:
        deleted = delete_campaign(campaign_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Campaign not found or is currently sending.",
        )

    return {"message": "Campaign deleted successfully."}


@app.post("/api/campaigns/{campaign_id}/send")
async def launch_campaign(campaign_id: int, background_tasks: BackgroundTasks):
    campaign = get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    settings = get_all_settings()
    if not is_google_connected() and not (settings.get("sender_email") and settings.get("smtp_password")):
        raise HTTPException(
            status_code=400,
            detail="Gmail account is not connected. Click 'Connect Google Account' in Settings."
        )

    approved = [
        r for r in campaign["recipients"]
        if r["review_status"] == "approved" and r.get("send_status") != "sent"
    ]

    if not approved:
        raise HTTPException(
            status_code=400,
            detail="No approved un-sent recipients in this campaign. Approve recipients first!"
        )

    # Launch background task
    background_tasks.add_task(run_campaign_send, campaign_id)

    return {
        "message": f"Sending started for {len(approved)} approved recipients via {'Google Gmail API' if is_google_connected() else 'SMTP'}.",
        "campaign_id": campaign_id,
        "approved_count": len(approved)
    }


@app.get("/api/campaigns/{campaign_id}/logs")
async def campaign_logs(campaign_id: int):
    logs = get_email_logs(campaign_id=campaign_id)
    return {"campaign_id": campaign_id, "total_logs": len(logs), "logs": logs}


@app.get("/api/campaigns/{campaign_id}/export")
async def export_campaign_logs(campaign_id: int):
    logs = get_email_logs(campaign_id=campaign_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Log ID", "Recipient Email", "Subject", "Status", "Error Message", "Sent At"])
    for log in logs:
        writer.writerow([
            log.get("id"),
            log.get("recipient_email"),
            log.get("subject"),
            log.get("status"),
            log.get("error_message") or "",
            log.get("sent_at")
        ])
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=campaign_{campaign_id}_delivery_logs.csv"}
    )


# --------------------------------------------------
# SETTINGS
# --------------------------------------------------

@app.get("/api/settings")
async def fetch_settings():
    settings = get_all_settings()
    google_connected = is_google_connected()
    google_user = get_authenticated_user_info() if google_connected else None

    has_smtp_password = bool(settings.get("smtp_password"))
    masked_pw = "••••••••••••••••" if has_smtp_password else ""

    connected_email = google_user["email"] if google_user else settings.get("sender_email", "")
    connected_name = (google_user["name"] if google_user else "") or settings.get("sender_name", "")

    return {
        "sender_name": connected_name,
        "sender_email": connected_email,
        "smtp_host": settings.get("smtp_host", "smtp.gmail.com"),
        "smtp_port": settings.get("smtp_port", "587"),
        "smtp_use_ssl": str(settings.get("smtp_use_ssl", "")).lower() in ("true", "1"),
        "delay_seconds": settings.get("delay_seconds", "3"),
        "daily_limit": settings.get("daily_limit", "50"),
        "has_password": has_smtp_password,
        "smtp_password": masked_pw,
        "is_google_connected": google_connected,
        "google_user": google_user,
        "is_configured": google_connected or bool(settings.get("sender_email") and has_smtp_password)
    }


@app.post("/api/settings")
async def update_settings(data: SettingsInput):
    set_setting("sender_name", data.sender_name.strip())
    set_setting("sender_email", data.sender_email.strip().lower())
    set_setting("smtp_host", data.smtp_host.strip())
    set_setting("smtp_port", str(data.smtp_port).strip())
    set_setting("smtp_use_ssl", "true" if data.smtp_use_ssl else "false")
    set_setting("delay_seconds", str(data.delay_seconds).strip())
    set_setting("daily_limit", str(data.daily_limit).strip())

    if data.smtp_password and not data.smtp_password.startswith("••••"):
        set_setting("smtp_password", data.smtp_password.strip().replace(" ", ""))

    return {"message": "Account settings updated successfully."}


@app.post("/api/settings/test-connection")
async def test_connection(data: TestEmailInput):
    if is_google_connected():
        return await test_google_connection()

    settings = get_all_settings()
    host = settings.get("smtp_host", "smtp.gmail.com")
    port = settings.get("smtp_port", "587")
    user = settings.get("sender_email", "").strip()
    pw = settings.get("smtp_password", "").strip()
    use_ssl = str(settings.get("smtp_use_ssl", "")).lower() in ("true", "1")

    if not user or not pw:
        raise HTTPException(
            status_code=400,
            detail="Save your Sender Email and Gmail App Password, or Connect with Google."
        )

    success, msg = test_smtp_connection(host, port, user, pw, use_ssl=use_ssl)
    if not success:
        raise HTTPException(status_code=400, detail=msg)

    target_email = (data.test_email or user).strip()
    if target_email:
        test_sub = "JobApply Mailer - SMTP Connection Test Successful! 🎉"
        test_body = (
            f"Hello {settings.get('sender_name') or 'Job Seeker'},\n\n"
            f"Your Gmail connection in JobApply Mailer is working properly!\n"
            f"You can now create campaigns, personalize application templates, and attach your resume automatically.\n\n"
            f"— JobApply Mailer Automation Engine"
        )
        sent, send_err = send_single_email_smtp(
            host=host,
            port=port,
            sender_email=user,
            sender_name=settings.get("sender_name", "JobApply Mailer"),
            password=pw,
            to_email=target_email,
            subject=test_sub,
            body_text=test_body,
            use_ssl=use_ssl
        )
        if not sent:
            raise HTTPException(
                status_code=400,
                detail=f"Authenticated, but could not deliver test email: {send_err}"
            )
        msg += f" A test verification email was sent to {target_email}!"

    return {"success": True, "message": msg}
