
import csv
import io
import re
import uuid
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
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
    get_email_template_count
)


# --------------------------------------------------
# APPLICATION CONFIGURATION
# --------------------------------------------------

app = FastAPI(
    title="JobApply Mailer",
    description="Smart Email Automation for Job Seekers",
    version="1.3.0"
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
# DASHBOARD
# --------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "title": "JobApply Mailer",
            "total_contacts": get_contact_count(),
            "resume": get_resume()
        }
    )


# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "running",
        "application": "JobApply Mailer"
    }


# --------------------------------------------------
# CONTACT MANAGEMENT
# --------------------------------------------------

@app.get("/api/contacts")
async def list_contacts():
    contacts = get_all_contacts()

    return {
        "total_contacts": len(contacts),
        "contacts": contacts
    }


@app.get("/api/contacts/search")
async def search_contacts(q: str = ""):
    contacts = get_all_contacts(q.strip())

    return {
        "total_contacts": len(contacts),
        "contacts": contacts
    }


@app.delete("/api/contacts/{contact_id}")
async def remove_contact(contact_id: int):
    deleted = delete_contact(contact_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Contact not found."
        )

    return {
        "message": "Contact deleted successfully.",
        "total_contacts": get_contact_count()
    }


@app.post("/api/contacts/upload")
async def upload_contacts(file: UploadFile = File(...)):

    filename = (file.filename or "").lower()

    if not filename.endswith((".csv", ".xlsx")):
        raise HTTPException(
            status_code=400,
            detail="Only CSV and XLSX files are supported."
        )

    content = await file.read()

    if not content:
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is empty."
        )

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail="File size must be 5 MB or less."
        )

    try:
        if filename.endswith(".csv"):
            rows = list(
                csv.reader(
                    io.StringIO(content.decode("utf-8-sig"))
                )
            )
        else:
            workbook = load_workbook(
                io.BytesIO(content),
                read_only=True,
                data_only=True
            )

            rows = list(
                workbook.active.iter_rows(values_only=True)
            )

            workbook.close()

    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Could not read this file. Check the file format."
        )

    if len(rows) < 2:
        raise HTTPException(
            status_code=400,
            detail="File needs a header and at least one contact."
        )

    headers = [
        str(value).strip().lower() if value is not None else ""
        for value in rows[0]
    ]

    email_columns = [
        i for i, header in enumerate(headers)
        if header in ("email", "email address", "e-mail", "mail")
    ]

    if not email_columns:
        raise HTTPException(
            status_code=400,
            detail="Add a column named Email."
        )

    email_index = email_columns[0]

    name_index = next(
        (
            i for i, header in enumerate(headers)
            if header in ("name", "full name", "contact name")
        ),
        None
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

        contacts.append({
            "name": name,
            "email": email
        })

    if not contacts:
        raise HTTPException(
            status_code=400,
            detail="No valid contacts found in the file."
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
        "contacts": contacts
    }


# --------------------------------------------------
# RESUME MANAGEMENT
# --------------------------------------------------

@app.get("/api/resume")
async def resume_status():
    resume = get_resume()

    if not resume:
        return {
            "uploaded": False,
            "message": "No resume uploaded yet."
        }

    return {
        "uploaded": True,
        "resume": {
            "id": resume["id"],
            "filename": resume["original_filename"],
            "file_type": resume["file_type"],
            "file_size": resume["file_size"],
            "uploaded_at": resume["uploaded_at"]
        }
    }


@app.post("/api/resume/upload")
async def upload_resume(file: UploadFile = File(...)):

    original_filename = Path(file.filename or "").name
    extension = Path(original_filename).suffix.lower()

    if extension not in (".pdf", ".docx"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF and DOCX resumes are supported."
        )

    content = await file.read()

    if not content:
        raise HTTPException(
            status_code=400,
            detail="The uploaded resume is empty."
        )

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail="Resume size must be 5 MB or less."
        )

    # Basic file signature validation.
    if extension == ".pdf" and not content.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=400,
            detail="The file does not appear to be a valid PDF."
        )

    if extension == ".docx" and not content.startswith(b"PK"):
        raise HTTPException(
            status_code=400,
            detail="The file does not appear to be a valid DOCX document."
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
            file_size=len(content)
        )

    except Exception:
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500,
            detail="Could not save the resume."
        )

    # Remove the previous stored file after the new resume is saved.
    if old_resume:
        old_file = RESUME_DIR / old_resume["stored_filename"]
        old_file.unlink(missing_ok=True)

    return {
        "message": "Resume uploaded successfully.",
        "resume": {
            "filename": original_filename,
            "file_type": extension.lstrip(".").upper(),
            "file_size": len(content)
        }
    }


@app.get("/api/resume/download")
async def download_resume():

    resume = get_resume()

    if not resume:
        raise HTTPException(
            status_code=404,
            detail="No resume has been uploaded."
        )

    file_path = RESUME_DIR / resume["stored_filename"]

    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Resume file is missing from storage."
        )

    media_type = (
        "application/pdf"
        if resume["file_type"] == "PDF"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=resume["original_filename"]
    )


@app.delete("/api/resume")
async def remove_resume():

    resume = get_resume()

    if not resume:
        raise HTTPException(
            status_code=404,
            detail="No resume has been uploaded."
        )

    deleted = delete_resume()

    if not deleted:
        raise HTTPException(
            status_code=500,
            detail="Could not delete resume information."
        )

    file_path = RESUME_DIR / resume["stored_filename"]
    file_path.unlink(missing_ok=True)

    return {
        "message": "Resume deleted successfully."
    }


# --------------------------------------------------
# EMAIL TEMPLATE VALIDATION
# --------------------------------------------------

class EmailTemplateInput(BaseModel):
    template_name: str = Field(min_length=1, max_length=100)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10000)


# --------------------------------------------------
# EMAIL TEMPLATE MANAGEMENT
# --------------------------------------------------

@app.get("/api/email-templates")
async def list_email_templates(search: str = ""):

    templates_list = get_all_email_templates(search.strip())

    return {
        "total_templates": len(templates_list),
        "templates": templates_list
    }


@app.get("/api/email-templates/{template_id}")
async def read_email_template(template_id: int):

    template = get_email_template(template_id)

    if not template:
        raise HTTPException(
            status_code=404,
            detail="Email template not found."
        )

    return template


@app.post("/api/email-templates")
async def add_email_template(data: EmailTemplateInput):

    template_id = create_email_template(
        data.template_name.strip(),
        data.subject.strip(),
        data.body.strip()
    )

    return {
        "message": "Email template created successfully.",
        "template_id": template_id,
        "total_templates": get_email_template_count()
    }


@app.put("/api/email-templates/{template_id}")
async def edit_email_template(
    template_id: int,
    data: EmailTemplateInput
):

    existing = get_email_template(template_id)

    if not existing:
        raise HTTPException(
            status_code=404,
            detail="Email template not found."
        )

    updated = update_email_template(
        template_id,
        data.template_name.strip(),
        data.subject.strip(),
        data.body.strip()
    )

    if not updated:
        raise HTTPException(
            status_code=500,
            detail="Could not update email template."
        )

    return {
        "message": "Email template updated successfully.",
        "template_id": template_id
    }


@app.delete("/api/email-templates/{template_id}")
async def remove_email_template(template_id: int):

    deleted = delete_email_template(template_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Email template not found."
        )

    return {
        "message": "Email template deleted successfully.",
        "total_templates": get_email_template_count()
    }


# --------------------------------------------------
# EMAIL TEMPLATE PREVIEW
# --------------------------------------------------

@app.post("/api/email-templates/{template_id}/preview")
async def preview_email_template(
    template_id: int,
    recruiter_name: str = "Hiring Team",
    sender_name: str = "Your Name",
    job_role: str = "Python Developer",
    company_name: str = "Company"
):

    template = get_email_template(template_id)

    if not template:
        raise HTTPException(
            status_code=404,
            detail="Email template not found."
        )

    replacements = {
        "{{recruiter_name}}": recruiter_name,
        "{{sender_name}}": sender_name,
        "{{job_role}}": job_role,
        "{{company_name}}": company_name
    }

    subject = template["subject"]
    body = template["body"]

    for placeholder, value in replacements.items():
        subject = subject.replace(placeholder, value)
        body = body.replace(placeholder, value)

    return {
        "template_id": template_id,
        "subject": subject,
        "body": body
    }
