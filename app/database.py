import sqlite3
from pathlib import Path


DATABASE_PATH = Path(__file__).resolve().parent.parent / "jobapply.db"


# --------------------------------------------------
# DATABASE CONNECTION
# --------------------------------------------------

def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


# --------------------------------------------------
# DATABASE INITIALIZATION
# --------------------------------------------------

def initialize_database():
    with get_connection() as connection:

        # Contacts table
        connection.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Resumes table
        connection.execute("""
            CREATE TABLE IF NOT EXISTS resumes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL UNIQUE,
                file_type TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Email templates table
        connection.execute("""
            CREATE TABLE IF NOT EXISTS email_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_name TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Campaigns table
        connection.execute("""
            CREATE TABLE IF NOT EXISTS campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_name TEXT NOT NULL,
                template_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'review', 'sending', 'completed', 'paused', 'cancelled')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (template_id)
                    REFERENCES email_templates(id)
                    ON DELETE RESTRICT
            )
        """)

        # Campaign recipients table
        connection.execute("""
            CREATE TABLE IF NOT EXISTS campaign_recipients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                contact_id INTEGER,
                recipient_name TEXT,
                recipient_email TEXT NOT NULL,
                review_status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (review_status IN ('pending', 'approved', 'suppressed')),
                send_status TEXT NOT NULL DEFAULT 'unattempted'
                    CHECK (send_status IN ('unattempted', 'sent', 'failed')),
                sent_at TIMESTAMP,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (campaign_id, recipient_email),
                FOREIGN KEY (campaign_id)
                    REFERENCES campaigns(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (contact_id)
                    REFERENCES contacts(id)
                    ON DELETE SET NULL
            )
        """)

        # Email logs table
        connection.execute("""
            CREATE TABLE IF NOT EXISTS email_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER,
                recipient_id INTEGER,
                recipient_email TEXT NOT NULL,
                subject TEXT,
                status TEXT NOT NULL CHECK (status IN ('sent', 'failed')),
                error_message TEXT,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
                FOREIGN KEY (recipient_id) REFERENCES campaign_recipients(id) ON DELETE SET NULL
            )
        """)

        # Settings key-value table
        connection.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Indices
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_campaigns_created_at
            ON campaigns(created_at)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_campaign_recipients_campaign
            ON campaign_recipients(campaign_id)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_email_logs_campaign
            ON email_logs(campaign_id)
        """)

        # Ensure schema migrations for existing tables if columns are missing
        # 1. Check campaign_recipients columns
        cursor = connection.execute("PRAGMA table_info(campaign_recipients)")
        existing_cols = {row["name"] for row in cursor.fetchall()}
        if "send_status" not in existing_cols:
            connection.execute("ALTER TABLE campaign_recipients ADD COLUMN send_status TEXT NOT NULL DEFAULT 'unattempted'")
        if "sent_at" not in existing_cols:
            connection.execute("ALTER TABLE campaign_recipients ADD COLUMN sent_at TIMESTAMP")
        if "error_message" not in existing_cols:
            connection.execute("ALTER TABLE campaign_recipients ADD COLUMN error_message TEXT")

        # 2. Check if campaigns check constraint allows 'sending' and 'completed'
        schema_row = connection.execute("SELECT sql FROM sqlite_master WHERE name='campaigns'").fetchone()
        if schema_row and ("sending" not in schema_row["sql"]):
            # Migrate campaigns table to support 'sending' and 'completed'
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("""
                CREATE TABLE campaigns_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_name TEXT NOT NULL,
                    template_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft', 'review', 'sending', 'completed', 'paused', 'cancelled')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (template_id)
                        REFERENCES email_templates(id)
                        ON DELETE RESTRICT
                )
            """)
            connection.execute("""
                INSERT INTO campaigns_new (id, campaign_name, template_id, status, created_at, updated_at)
                SELECT id, campaign_name, template_id, status, created_at, updated_at FROM campaigns
            """)
            connection.execute("DROP TABLE campaigns")
            connection.execute("ALTER TABLE campaigns_new RENAME TO campaigns")
            connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_campaigns_created_at ON campaigns(created_at)
            """)
            connection.execute("PRAGMA foreign_keys = ON")


# --------------------------------------------------
# CONTACT MANAGEMENT
# --------------------------------------------------

def save_contacts(contacts):
    saved_count = 0
    already_saved = 0

    with get_connection() as connection:
        for contact in contacts:
            cursor = connection.execute("""
                INSERT OR IGNORE INTO contacts (name, email)
                VALUES (?, ?)
            """, (contact["name"], contact["email"]))

            if cursor.rowcount == 1:
                saved_count += 1
            else:
                already_saved += 1

    return saved_count, already_saved


def get_all_contacts(search=""):
    with get_connection() as connection:
        if search:
            rows = connection.execute("""
                SELECT id, name, email, created_at
                FROM contacts
                WHERE name LIKE ? OR email LIKE ?
                ORDER BY id DESC
            """, (f"%{search}%", f"%{search}%")).fetchall()
        else:
            rows = connection.execute("""
                SELECT id, name, email, created_at
                FROM contacts
                ORDER BY id DESC
            """).fetchall()

    return [dict(row) for row in rows]


def get_contact_count():
    with get_connection() as connection:
        result = connection.execute(
            "SELECT COUNT(*) FROM contacts"
        ).fetchone()
    return result[0]


def delete_contact(contact_id):
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM contacts WHERE id = ?",
            (contact_id,)
        )
    return cursor.rowcount > 0


# --------------------------------------------------
# RESUME MANAGEMENT
# --------------------------------------------------

def save_resume(original_filename, stored_filename, file_type, file_size):
    with get_connection() as connection:
        connection.execute("DELETE FROM resumes")
        connection.execute("""
            INSERT INTO resumes (
                original_filename, stored_filename, file_type, file_size
            )
            VALUES (?, ?, ?, ?)
        """, (original_filename, stored_filename, file_type, file_size))


def get_resume():
    with get_connection() as connection:
        row = connection.execute("""
            SELECT id, original_filename, stored_filename,
                   file_type, file_size, uploaded_at
            FROM resumes
            ORDER BY id DESC
            LIMIT 1
        """).fetchone()
    return dict(row) if row else None


def delete_resume():
    with get_connection() as connection:
        cursor = connection.execute("DELETE FROM resumes")
    return cursor.rowcount > 0


# --------------------------------------------------
# EMAIL TEMPLATE MANAGEMENT
# --------------------------------------------------

def create_email_template(template_name, subject, body):
    with get_connection() as connection:
        cursor = connection.execute("""
            INSERT INTO email_templates (template_name, subject, body)
            VALUES (?, ?, ?)
        """, (template_name.strip(), subject.strip(), body.strip()))
        return cursor.lastrowid


def get_all_email_templates(search=""):
    with get_connection() as connection:
        if search:
            rows = connection.execute("""
                SELECT id, template_name, subject, body,
                       created_at, updated_at
                FROM email_templates
                WHERE template_name LIKE ? OR subject LIKE ?
                ORDER BY id DESC
            """, (f"%{search}%", f"%{search}%")).fetchall()
        else:
            rows = connection.execute("""
                SELECT id, template_name, subject, body,
                       created_at, updated_at
                FROM email_templates
                ORDER BY id DESC
            """).fetchall()
    return [dict(row) for row in rows]


def get_email_template(template_id):
    with get_connection() as connection:
        row = connection.execute("""
            SELECT *
            FROM email_templates
            WHERE id = ?
        """, (template_id,)).fetchone()
    return dict(row) if row else None


def update_email_template(template_id, template_name, subject, body):
    with get_connection() as connection:
        cursor = connection.execute("""
            UPDATE email_templates
            SET template_name = ?,
                subject = ?,
                body = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (template_name.strip(), subject.strip(), body.strip(), template_id))
    return cursor.rowcount > 0


def delete_email_template(template_id):
    with get_connection() as connection:
        cursor = connection.execute("""
            DELETE FROM email_templates
            WHERE id = ?
        """, (template_id,))
    return cursor.rowcount > 0


def get_email_template_count():
    with get_connection() as connection:
        result = connection.execute(
            "SELECT COUNT(*) FROM email_templates"
        ).fetchone()
    return result[0]


# --------------------------------------------------
# CAMPAIGN MANAGEMENT
# --------------------------------------------------

def create_campaign(campaign_name, template_id, contact_ids):
    campaign_name = campaign_name.strip()
    unique_ids = list(dict.fromkeys(int(value) for value in contact_ids))

    if not campaign_name:
        raise ValueError("Campaign name is required.")

    if not unique_ids:
        raise ValueError("Select at least one recipient.")

    with get_connection() as connection:
        template = connection.execute(
            "SELECT id FROM email_templates WHERE id = ?",
            (template_id,)
        ).fetchone()

        if not template:
            raise ValueError("Selected email template does not exist.")

        placeholders = ",".join("?" for _ in unique_ids)
        contacts = connection.execute(
            f"""SELECT id, name, email FROM contacts
                WHERE id IN ({placeholders}) ORDER BY id""",
            unique_ids
        ).fetchall()

        found_ids = {row["id"] for row in contacts}
        missing_ids = set(unique_ids) - found_ids
        if missing_ids:
            raise ValueError(
                "Some selected contacts no longer exist: "
                + ", ".join(str(value) for value in sorted(missing_ids))
            )

        cursor = connection.execute("""
            INSERT INTO campaigns (campaign_name, template_id, status)
            VALUES (?, ?, 'draft')
        """, (campaign_name, template_id))
        campaign_id = cursor.lastrowid

        for contact in contacts:
            connection.execute("""
                INSERT INTO campaign_recipients (
                    campaign_id, contact_id, recipient_name, recipient_email
                )
                VALUES (?, ?, ?, ?)
            """, (
                campaign_id,
                contact["id"],
                contact["name"],
                contact["email"]
            ))

    return campaign_id


def get_all_campaigns():
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT
                c.id,
                c.campaign_name,
                c.template_id,
                t.template_name,
                c.status,
                c.created_at,
                c.updated_at,
                COUNT(r.id) AS recipient_count,
                SUM(CASE WHEN r.send_status = 'sent' THEN 1 ELSE 0 END) AS sent_count,
                SUM(CASE WHEN r.send_status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
                SUM(CASE WHEN r.review_status = 'approved' THEN 1 ELSE 0 END) AS approved_count
            FROM campaigns c
            JOIN email_templates t ON t.id = c.template_id
            LEFT JOIN campaign_recipients r ON r.campaign_id = c.id
            GROUP BY c.id
            ORDER BY c.id DESC
        """).fetchall()
    return [dict(row) for row in rows]


def get_campaign(campaign_id):
    with get_connection() as connection:
        campaign = connection.execute("""
            SELECT
                c.id,
                c.campaign_name,
                c.template_id,
                t.template_name,
                t.subject AS template_subject,
                t.body AS template_body,
                c.status,
                c.created_at,
                c.updated_at
            FROM campaigns c
            JOIN email_templates t ON t.id = c.template_id
            WHERE c.id = ?
        """, (campaign_id,)).fetchone()

        if not campaign:
            return None

        recipients = connection.execute("""
            SELECT id, contact_id, recipient_name, recipient_email,
                   review_status, send_status, sent_at, error_message, created_at
            FROM campaign_recipients
            WHERE campaign_id = ?
            ORDER BY id
        """, (campaign_id,)).fetchall()

    result = dict(campaign)
    result["recipients"] = [dict(row) for row in recipients]
    return result


def update_campaign_status(campaign_id, status):
    allowed_statuses = {"draft", "review", "sending", "completed", "paused", "cancelled"}
    if status not in allowed_statuses:
        raise ValueError("Invalid campaign status.")

    with get_connection() as connection:
        cursor = connection.execute("""
            UPDATE campaigns
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (status, campaign_id))
    return cursor.rowcount > 0


def update_campaign_recipient_status(recipient_id, review_status):
    allowed_statuses = {"pending", "approved", "suppressed"}
    if review_status not in allowed_statuses:
        raise ValueError("Invalid recipient review status.")

    with get_connection() as connection:
        cursor = connection.execute("""
            UPDATE campaign_recipients
            SET review_status = ?
            WHERE id = ?
        """, (review_status, recipient_id))
    return cursor.rowcount > 0


def update_campaign_recipient_send_status(recipient_id, send_status, error_message=None):
    allowed_statuses = {"unattempted", "sent", "failed"}
    if send_status not in allowed_statuses:
        raise ValueError("Invalid recipient send status.")

    with get_connection() as connection:
        cursor = connection.execute("""
            UPDATE campaign_recipients
            SET send_status = ?,
                sent_at = CASE WHEN ? = 'sent' THEN CURRENT_TIMESTAMP ELSE sent_at END,
                error_message = ?
            WHERE id = ?
        """, (send_status, send_status, error_message, recipient_id))
    return cursor.rowcount > 0


def delete_campaign(campaign_id):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT status FROM campaigns WHERE id = ?",
            (campaign_id,)
        ).fetchone()

        if not row:
            return False

        if row["status"] in ("sending",):
            raise ValueError("Cannot delete a campaign that is currently sending.")

        cursor = connection.execute(
            "DELETE FROM campaigns WHERE id = ?",
            (campaign_id,)
        )
    return cursor.rowcount > 0


def get_campaign_count():
    with get_connection() as connection:
        result = connection.execute(
            "SELECT COUNT(*) FROM campaigns"
        ).fetchone()
    return result[0]


# --------------------------------------------------
# SETTINGS MANAGEMENT
# --------------------------------------------------

DEFAULT_SETTINGS = {
    "sender_name": "JYOTHI ADITYA GIRI JELLI",
    "sender_email": "",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": "587",
    "smtp_use_ssl": "false",
    "smtp_password": "",
    "delay_seconds": "3",
    "daily_limit": "50"
}


def get_setting(key, default=None):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,)
        ).fetchone()
        if row and row["value"] is not None:
            return row["value"]
    return default if default is not None else DEFAULT_SETTINGS.get(key, "")


def set_setting(key, value):
    with get_connection() as connection:
        connection.execute("""
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
        """, (key, str(value)))


def get_all_settings():
    settings = dict(DEFAULT_SETTINGS)
    with get_connection() as connection:
        rows = connection.execute("SELECT key, value FROM settings").fetchall()
        for r in rows:
            settings[r["key"]] = r["value"]
    return settings


# --------------------------------------------------
# EMAIL LOGS & DELIVERY STATS
# --------------------------------------------------

def log_email_send(campaign_id, recipient_id, recipient_email, subject, status, error_message=None):
    with get_connection() as connection:
        connection.execute("""
            INSERT INTO email_logs (
                campaign_id, recipient_id, recipient_email,
                subject, status, error_message
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (campaign_id, recipient_id, recipient_email, subject, status, error_message))


def get_email_logs(campaign_id=None, limit=100):
    with get_connection() as connection:
        if campaign_id:
            rows = connection.execute("""
                SELECT * FROM email_logs
                WHERE campaign_id = ?
                ORDER BY id DESC
                LIMIT ?
            """, (campaign_id, limit)).fetchall()
        else:
            rows = connection.execute("""
                SELECT * FROM email_logs
                ORDER BY id DESC
                LIMIT ?
            """, (limit,)).fetchall()
    return [dict(row) for row in rows]


def get_total_sent_count():
    with get_connection() as connection:
        result = connection.execute("""
            SELECT COUNT(*) FROM email_logs WHERE status = 'sent'
        """).fetchone()
    return result[0]
