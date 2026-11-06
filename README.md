# 🚀 JobApply Mailer

Smart Email Automation Platform for Job Seekers.

JobApply Mailer helps software engineers and job seekers organize recruiter leads, manage professional resumes, create personalized application templates, and run targeted, safe email outreach campaigns directly through Gmail.

---

## ✨ Features

- **📋 Recruiter Contact Management**: Upload hundreds of contacts via CSV or Excel (`.xlsx`) with automated email validation, duplicate detection, and instant search. Download ready-to-fill sample CSV templates with one click.
- **📄 Smart Resume Storage**: Upload and manage your primary PDF or DOCX resume with file integrity verification. Resumes are automatically attached to outgoing job applications.
- **✉️ Template Personalization Engine**: Build templates with dynamic placeholders (`{{recruiter_name}}`, `{{sender_name}}`, `{{job_role}}`, `{{company_name}}`) and preview rendered messages before sending.
- **🚀 Campaign Outreach & Staging**:
  - Group contacts into targeted campaigns (e.g., "Full Stack Developer - Bangalore", "Fresher SDE - Remote").
  - **Recipient Review**: Approve or suppress individual contacts before sending.
  - **Safe Delivery Queue**: Background email delivery with configurable delays (2–5 seconds) between emails to maintain strong domain reputation and avoid spam filters.
  - **Delivery Tracking**: Track real-time send states (`sent`, `failed`, `unattempted`) and export audit logs to CSV.
- **⚙️ Secure Gmail SMTP Integration**: Connect via Google App Passwords without sharing account passwords. Includes built-in connection testing and verification email delivery.

---

## 🛠️ Tech Stack

- **Backend**: Python 3.10+ / FastAPI / Uvicorn
- **Database**: SQLite3 (zero-configuration, high-performance local relational storage)
- **Frontend**: Responsive HTML5, Vanilla JavaScript, Jinja2 Templates (no heavy npm build steps required)
- **File Parsing**: OpenPyXL, Python CSV
- **Email Engine**: Standard library `smtplib`, `email.mime` with multipart attachment handling

---

## 🚀 Quickstart Guide

### 1. Open Terminal & Navigate to Project

```powershell
cd C:\Users\adity\JobApplyMailer
```

### 2. Activate Virtual Environment (or run directly)

```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 3. Open the Dashboard

Open your browser to:
- **Web Dashboard**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **Interactive Swagger API Docs**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## 🔑 Setting up Gmail (2-Minute Guide)

To send emails from your personal Gmail account:

1. Go to your [Google Account Security Settings](https://myaccount.google.com/security).
2. Ensure **2-Step Verification** is turned ON.
3. Open [Google App Passwords](https://myaccount.google.com/apppasswords).
4. Enter an app name (e.g., `JobApplyMailer`) and click **Create**.
5. Copy the 16-character password provided.
6. In JobApply Mailer, open **Settings & Gmail** on the left menu:
   - Enter your name and Gmail address.
   - Paste the 16-character App Password.
   - Click **Save Account Settings**.
   - Click **⚡ Test Connection & Send Verification Email** to confirm everything is working!

---

## 📂 Project Structure

```text
JobApplyMailer/
├── app/
│   ├── database.py       # SQLite connection, schema & CRUD queries
│   ├── mailer.py         # SMTP delivery, resume attachments & background sending
│   ├── main.py           # FastAPI REST API routes & dashboard template renderer
│   ├── templates/
│   │   └── dashboard.html# Single-page modern dashboard UI
│   └── uploads/
│       └── resumes/      # Secure storage for uploaded resumes
├── jobapply.db           # SQLite database
├── test_contacts.csv     # Sample contact list
├── requirements.txt      # Python dependencies
└── README.md             # Documentation
```

---

## 🛡️ Best Practices for Cold Job Inquiries

1. **Keep Daily Batches Reasonable**: Start with 20–50 applications per day.
2. **Review Every Contact**: Use the campaign review table to verify each recruiter's name and company before hitting send.
3. **Respect Sending Delays**: The default 3-second delay between emails helps prevent Gmail rate limits.
4. **Tailor Your Subject Lines**: Clear, personalized subjects like *"Application for Software Engineer - Jyothi Aditya"* achieve the highest open rates.
