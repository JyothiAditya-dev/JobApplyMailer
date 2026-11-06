import json
import os
import requests
from urllib.parse import urlencode
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from app.database import set_setting

BASE_DIR = Path(__file__).resolve().parent.parent
CLIENT_SECRET_FILE = BASE_DIR / "client_secret.json"
TOKEN_FILE = BASE_DIR / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid"
]


def load_client_secrets():
    # 1. Check environment variable (recommended for cloud deployments like Render/Railway)
    env_json = os.environ.get("GOOGLE_CLIENT_SECRET_JSON")
    if env_json:
        try:
            data = json.loads(env_json)
            cfg = data.get("installed") or data.get("web")
            if cfg:
                return cfg
        except Exception:
            pass

    # 2. Check local file
    if not CLIENT_SECRET_FILE.is_file():
        raise FileNotFoundError("client_secret.json is missing and GOOGLE_CLIENT_SECRET_JSON environment variable is not set.")

    data = json.loads(CLIENT_SECRET_FILE.read_text(encoding="utf-8"))
    cfg = data.get("installed") or data.get("web")
    if not cfg:
        raise ValueError("Invalid client_secret.json: neither 'installed' nor 'web' config found.")
    return cfg


def get_authorization_url(redirect_uri: str) -> str:
    """
    Constructs the official Google OAuth 2.0 authorization URL.
    """
    cfg = load_client_secrets()
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true"
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def exchange_code_for_token(code: str, redirect_uri: str) -> dict:
    """
    Exchanges authorization code for tokens and saves token.json.
    Fetches and returns user info (email, name).
    """
    cfg = load_client_secrets()

    token_payload = {
        "code": code,
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }

    token_resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data=token_payload,
        timeout=15
    )

    if not token_resp.ok:
        err_msg = token_resp.text
        try:
            err_msg = token_resp.json().get("error_description", token_resp.text)
        except Exception:
            pass
        raise ValueError(f"Failed to exchange Google OAuth code: {err_msg}")

    token_data = token_resp.json()

    # Build standard Google Credentials payload for token.json
    creds_data = {
        "token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token"),
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "scopes": SCOPES
    }

    # Fetch UserInfo
    headers = {"Authorization": f"Bearer {token_data['access_token']}"}
    userinfo_resp = requests.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers=headers,
        timeout=15
    )

    user_info = {}
    if userinfo_resp.ok:
        user_info = userinfo_resp.json()
        if user_info.get("email"):
            set_setting("sender_email", user_info["email"])
        if user_info.get("name"):
            set_setting("sender_name", user_info["name"])

    TOKEN_FILE.write_text(json.dumps(creds_data, indent=2), encoding="utf-8")

    return {
        "email": user_info.get("email"),
        "name": user_info.get("name"),
        "picture": user_info.get("picture")
    }


def get_google_credentials():
    """
    Returns valid Credentials if token.json exists and is valid (or refreshed).
    Returns None if not authenticated.
    """
    if not TOKEN_FILE.is_file():
        return None

    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    except Exception as e:
        print(f"Error loading token.json: {e}")
        return None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        except Exception as e:
            print(f"Error refreshing credentials: {e}")
            return None

    if creds and creds.valid:
        return creds

    return None


def is_google_connected() -> bool:
    creds = get_google_credentials()
    return creds is not None and creds.valid


def get_authenticated_user_info():
    """
    Fetches the authenticated user's email and name via Google UserInfo API.
    """
    creds = get_google_credentials()
    if not creds:
        return None

    try:
        headers = {"Authorization": f"Bearer {creds.token}"}
        resp = requests.get("https://www.googleapis.com/oauth2/v2/userinfo", headers=headers, timeout=10)
        if resp.ok:
            data = resp.json()
            return {
                "email": data.get("email"),
                "name": data.get("name"),
                "picture": data.get("picture")
            }
    except Exception as e:
        print(f"Error fetching user info: {e}")

    return None


def disconnect_google():
    """
    Removes token.json to disconnect the Google account.
    """
    TOKEN_FILE.unlink(missing_ok=True)
