import os, re, json, webbrowser
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, redirect, url_for, jsonify, render_template_string
from authlib.integrations.flask_client import OAuth
import requests

load_dotenv()
APP = Flask(__name__)
APP.secret_key = os.urandom(32)

CLIENT_ID = os.getenv("INTUIT_CLIENT_ID")
CLIENT_SECRET = os.getenv("INTUIT_CLIENT_SECRET")
REDIRECT_URI = os.getenv("INTUIT_REDIRECT_URI", "http://localhost:5000/callback")
QBO_ENV = (os.getenv("QBO_ENV", "sandbox") or "sandbox").lower()
ENV_FILE = Path(".env")

AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
API_BASE = "https://sandbox-quickbooks.api.intuit.com" if QBO_ENV == "sandbox" else "https://quickbooks.api.intuit.com"
SCOPE = "com.intuit.quickbooks.accounting"

oauth = OAuth(APP)
intuit = oauth.register(
    name="intuit",
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    authorize_url=AUTH_URL,
    access_token_url=TOKEN_URL,
    api_base_url=API_BASE,
    client_kwargs={"scope": SCOPE},
)

def upsert_env(kv: dict):
    """Add or replace keys in .env (keeps other lines intact)."""
    text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    for k, v in kv.items():
        pattern = re.compile(rf"^{re.escape(k)}=.*?$", flags=re.MULTILINE)
        line = f"{k}={v}"
        if pattern.search(text):
            text = pattern.sub(line, text)
        else:
            if text and not text.endswith("\n"):
                text += "\n"
            text += line + "\n"
    ENV_FILE.write_text(text, encoding="utf-8")

def token_summary(token: dict):
    return {
        "saved_at_utc": datetime.utcnow().isoformat() + "Z",
        "access_len": len(token.get("access_token", "")),
        "has_refresh": bool(token.get("refresh_token")),
        "expires_in": token.get("expires_in"),
        "x_refresh_token_expires_in": token.get("x_refresh_token_expires_in"),
        "realmId": token.get("realmId"),
    }

HOME = """
<!doctype html>
<html>
  <body style="font-family: system-ui; max-width: 720px; margin: 2rem auto;">
    <h1>QBO OAuth → .env</h1>
    <p><a href="{{ url_for('start') }}" style="padding:10px 14px;background:#111;color:#fff;text-decoration:none;border-radius:6px;">Authenticate in Browser</a></p>
    <p>
      <a href="{{ url_for('refresh_tokens') }}">Refresh & Save to .env</a> |
      <a href="{{ url_for('peek') }}">Peek (.env token summary)</a>
    </p>
    <hr/>
    <p>Redirect URI must match: <code>{{ redirect_uri }}</code></p>
  </body>
</html>
"""

@APP.route("/")
def home():
    return render_template_string(HOME, redirect_uri=REDIRECT_URI)

@APP.route("/start")
def start():
    # Launch OAuth (same as Postman's "Generate Access Token" UX)
    return intuit.authorize_redirect(REDIRECT_URI, prompt="consent")

@APP.route("/callback")
def callback():
    # Intuit sends ?code=...&realmId=...&state=...
    token = intuit.authorize_access_token()
    realm_id = request.args.get("realmId")
    if realm_id:
        token["realmId"] = realm_id

    # Save to .env (Postman-like behavior)
    upsert_env({
        "QBO_ACCESS_TOKEN": token.get("access_token", ""),
        "QBO_REFRESH_TOKEN": token.get("refresh_token", ""),
        "QBO_REALM_ID": token.get("realmId", ""),
    })
    return redirect(url_for("peek"))

@APP.route("/refresh")
def refresh_tokens():
    # Use current refresh token from env
    load_dotenv(override=True)
    refresh_token = os.getenv("QBO_REFRESH_TOKEN", "")
    if not refresh_token:
        return jsonify({"error": "No QBO_REFRESH_TOKEN in .env. Authenticate first via /start."}), 400

    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    r = requests.post(
        TOKEN_URL,
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        auth=(CLIENT_ID, CLIENT_SECRET),
        data=data,
        timeout=30,
    )
    if r.status_code != 200:
        return jsonify({"error": "Refresh failed", "status": r.status_code, "body": r.text}), 400

    new_tok = r.json()  # contains new access_token and a ROTATED refresh_token
    # Preserve realmId if not returned
    realm_id = os.getenv("QBO_REALM_ID", "")
    upsert_env({
        "QBO_ACCESS_TOKEN": new_tok.get("access_token", ""),
        "QBO_REFRESH_TOKEN": new_tok.get("refresh_token", ""),
        "QBO_REALM_ID": realm_id,
    })
    return jsonify({"message": "Tokens refreshed & saved to .env", "summary": token_summary({**new_tok, "realmId": realm_id})})

@APP.route("/peek")
def peek():
    # Show a redacted summary of what’s in .env
    load_dotenv(override=True)
    at = os.getenv("QBO_ACCESS_TOKEN", "")
    rt = os.getenv("QBO_REFRESH_TOKEN", "")
    rid = os.getenv("QBO_REALM_ID", "")
    return jsonify({
        "QBO_REALM_ID": rid,
        "QBO_ACCESS_TOKEN": (at[:8] + "..." + at[-8:]) if at else "",
        "QBO_REFRESH_TOKEN": (rt[:8] + "..." + rt[-8:]) if rt else "",
    })

if __name__ == "__main__":
    webbrowser.open("http://localhost:5000", new=2)
    APP.run(host="127.0.0.1", port=5000)
