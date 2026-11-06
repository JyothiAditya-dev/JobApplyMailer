
import sqlite3
from pathlib import Path


DATABASE_PATH = Path(__file__).resolve().parent.parent / "jobapply.db"


# --------------------------------------------------
# DATABASE CONNECTION
# --------------------------------------------------

def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
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
            """, (
                contact["name"],
                contact["email"]
            ))

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
            """, (
                f"%{search}%",
                f"%{search}%"
            )).fetchall()

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

def save_resume(
    original_filename,
    stored_filename,
    file_type,
    file_size
):

    with get_connection() as connection:

        # Keep only the latest resume for this MVP.
        connection.execute("DELETE FROM resumes")

        connection.execute("""
            INSERT INTO resumes (
                original_filename,
                stored_filename,
                file_type,
                file_size
            )
            VALUES (?, ?, ?, ?)
        """, (
            original_filename,
            stored_filename,
            file_type,
            file_size
        ))


def get_resume():

    with get_connection() as connection:

        row = connection.execute("""
            SELECT
                id,
                original_filename,
                stored_filename,
                file_type,
                file_size,
                uploaded_at
            FROM resumes
            ORDER BY id DESC
            LIMIT 1
        """).fetchone()

    return dict(row) if row else None


def delete_resume():

    with get_connection() as connection:

        cursor = connection.execute(
            "DELETE FROM resumes"
        )

    return cursor.rowcount > 0


# --------------------------------------------------
# EMAIL TEMPLATE MANAGEMENT
# --------------------------------------------------

def create_email_template(template_name, subject, body):

    with get_connection() as connection:

        cursor = connection.execute("""
            INSERT INTO email_templates (
                template_name,
                subject,
                body
            )
            VALUES (?, ?, ?)
        """, (
            template_name.strip(),
            subject.strip(),
            body.strip()
        ))

        return cursor.lastrowid


def get_all_email_templates(search=""):

    with get_connection() as connection:

        if search:

            rows = connection.execute("""
                SELECT
                    id,
                    template_name,
                    subject,
                    body,
                    created_at,
                    updated_at
                FROM email_templates
                WHERE template_name LIKE ?
                   OR subject LIKE ?
                ORDER BY id DESC
            """, (
                f"%{search}%",
                f"%{search}%"
            )).fetchall()

        else:

            rows = connection.execute("""
                SELECT
                    id,
                    template_name,
                    subject,
                    body,
                    created_at,
                    updated_at
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


def update_email_template(
    template_id,
    template_name,
    subject,
    body
):

    with get_connection() as connection:

        cursor = connection.execute("""
            UPDATE email_templates
            SET
                template_name = ?,
                subject = ?,
                body = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            template_name.strip(),
            subject.strip(),
            body.strip(),
            template_id
        ))

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

        result = connection.execute("""
            SELECT COUNT(*)
            FROM email_templates
        """).fetchone()

    return result[0]
