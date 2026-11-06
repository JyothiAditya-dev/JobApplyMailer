"""
JobApply Mailer - Standalone Google Authentication Helper
Run this script to authenticate your Gmail account directly from your terminal:
    .\\venv\\Scripts\\python.exe authenticate_google.py
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from google_auth_oauthlib.flow import InstalledAppFlow
from app.google_auth import CLIENT_SECRET_FILE, TOKEN_FILE, SCOPES, get_authenticated_user_info
from app.database import set_setting, initialize_database

def main():
    print("=" * 65)
    print(" JobApply Mailer - Official Google Account Connection")
    print("=" * 65)

    if not CLIENT_SECRET_FILE.is_file():
        print(f"\n[ERROR] client_secret.json not found in {BASE_DIR}")
        print("Please ensure client_secret.json exists before authenticating.")
        sys.exit(1)

    print("\nStarting local authentication server...")
    print("Opening Google OAuth consent screen in your web browser...")
    print("Please select your Google account and click 'Allow' / 'Continue'.\n")

    try:
        initialize_database()
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CLIENT_SECRET_FILE),
            scopes=SCOPES
        )
        creds = flow.run_local_server(
            port=0,
            prompt="consent",
            authorization_prompt_message="Visit this URL in your browser to authorize JobApply Mailer: {url}",
            success_message="Authentication successful! You can close this browser tab and return to JobApply Mailer."
        )

        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        print("\n Credentials successfully saved to token.json!")

        # Fetch profile
        user = get_authenticated_user_info()
        if user and user.get("email"):
            set_setting("sender_email", user["email"])
            if user.get("name"):
                set_setting("sender_name", user["name"])
            print(f" Connected Account: {user['email']}")
            if user.get("name"):
                print(f" Sender Name:      {user['name']}")
        
        print("\n[SUCCESS] Your Gmail account is now connected via the official Gmail API (HTTPS/443).")
        print("You can now start JobApply Mailer and send emails safely!\n")

    except Exception as e:
        print(f"\n[ERROR] Authentication failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
