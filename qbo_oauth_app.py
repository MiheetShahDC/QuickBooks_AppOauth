import os
from datetime import datetime, timezone, timedelta

import requests
import psycopg2
from dotenv import load_dotenv
from flask import Flask, request, render_template_string
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix

# ------------------------------------------------------------------
# App setup
# ------------------------------------------------------------------
load_dotenv()

APP = Flask(__name__)
APP.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(32))

APP.wsgi_app = ProxyFix(APP.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

APP.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=90),
)

CLIENT_ID = os.getenv("INTUIT_CLIENT_ID")
CLIENT_SECRET = os.getenv("INTUIT_CLIENT_SECRET")
REDIRECT_URI = os.getenv("INTUIT_REDIRECT_URI")

_raw_env = (os.getenv("QBO_ENV", "sandbox") or "sandbox").strip().lower()
if _raw_env in ("production", "prod"):
    QBO_ENV = "prod"
elif _raw_env == "sandbox":
    QBO_ENV = "sandbox"
else:
    QBO_ENV = _raw_env

AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
USERINFO_URL = "https://accounts.platform.intuit.com/v1/openid_connect/userinfo"

API_BASE = (
    "https://sandbox-quickbooks.api.intuit.com"
    if QBO_ENV == "sandbox"
    else "https://quickbooks.api.intuit.com"
)

SCOPE = "com.intuit.quickbooks.accounting openid email profile"

RETURN_URL = (
    "https://datachamp-finance-58111015615.asia-south1.run.app/"
    "dashboard/sourceintegration"
)

LOGO_URL = "https://datachamps.ai/wp-content/uploads/2022/02/datachamp-logo.png"

WAIT_PAGE_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>FinSight360</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    body {
      margin: 0;
      height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #ffffff;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #1f2937;
    }
    .container {
      text-align: center;
      padding: 24px;
    }
    .logo {
      max-width: 240px;
      width: 100%;
      height: auto;
      margin-bottom: 24px;
    }
    .text {
      font-size: 20px;
      font-weight: 600;
      line-height: 1.4;
    }
  </style>
</head>
<body>
  <div class="container">
    <img class="logo" src="{{ logo_url }}" alt="Datachamps Logo" />
    <div class="text">FinSight360 is connecting to QuickBooks</div>
    <script>
      setTimeout(function() {
        window.location.href = "{{ redirect_url }}";
      }, 2000);
    </script>
  </div>
</body>
</html>
"""

# ------------------------------------------------------------------
# OAuth client
# ------------------------------------------------------------------
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

# ------------------------------------------------------------------
# Database helpers
# ------------------------------------------------------------------
def get_db_conn():
    return psycopg2.connect(
        host=os.getenv("PG_HOST"),
        port=os.getenv("PG_PORT", 5432),
        dbname=os.getenv("PG_DATABASE"),
        user=os.getenv("PG_USER"),
        password=os.getenv("PG_PASSWORD"),
    )


def render_wait_page(redirect_url: str):
    return render_template_string(
        WAIT_PAGE_HTML,
        redirect_url=redirect_url,
        logo_url=LOGO_URL,
    )


def upsert_qbo_token(
    token: dict,
    realm_id: str,
    tenant_id: str,
    intuit_email: str = None,
    intuit_user_id: str = None,
):
    conn = get_db_conn()
    cur = conn.cursor()

    issued_at = datetime.now(timezone.utc)
    expires_in = token.get("expires_in")
    refresh_expires_in = token.get("x_refresh_token_expires_in")

    access_expiry = issued_at.timestamp() + expires_in if expires_in else None
    refresh_expiry = issued_at.timestamp() + refresh_expires_in if refresh_expires_in else None

    cur.execute(
        """
        INSERT INTO config.qbo_oauth_tokens (
            tenant_id,
            realm_id,
            intuit_user_id,
            intuit_email,
            access_token,
            refresh_token,
            token_type,
            expires_in,
            refresh_expires_in,
            issued_at_utc,
            access_token_expires_at,
            refresh_token_expires_at,
            qbo_environment,
            client_id,
            created_at,
            updated_at
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),to_timestamp(%s),%s,%s,now(),now())
        ON CONFLICT (tenant_id, realm_id, qbo_environment)
        DO UPDATE SET
            access_token = EXCLUDED.access_token,
            refresh_token = EXCLUDED.refresh_token,
            expires_in = EXCLUDED.expires_in,
            refresh_expires_in = EXCLUDED.refresh_expires_in,
            issued_at_utc = EXCLUDED.issued_at_utc,
            access_token_expires_at = EXCLUDED.access_token_expires_at,
            refresh_token_expires_at = EXCLUDED.refresh_token_expires_at,
            intuit_user_id = EXCLUDED.intuit_user_id,
            intuit_email = EXCLUDED.intuit_email,
            updated_at = now();
        """,
        (
            tenant_id,
            realm_id,
            intuit_user_id,
            intuit_email,
            token.get("access_token"),
            token.get("refresh_token"),
            token.get("token_type", "bearer"),
            expires_in,
            refresh_expires_in,
            issued_at,
            access_expiry,
            refresh_expiry,
            QBO_ENV,
            CLIENT_ID,
        ),
    )

    conn.commit()
    cur.close()
    conn.close()


def upsert_tenant_qbo_mapping(
    tenant_id: str,
    realm_id: str,
):
    conn = get_db_conn()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO config.tenant_qbo_mapping (
            tenant_id,
            realm_id,
            qbo_environment,
            active,
            created_at,
            updated_at
        )
        VALUES (%s,%s,%s,%s,now(),now())
        ON CONFLICT (tenant_id, realm_id, qbo_environment)
        DO UPDATE SET
            active = EXCLUDED.active,
            updated_at = now();
        """,
        (
            tenant_id,
            realm_id,
            QBO_ENV,
            True,
        ),
    )

    conn.commit()
    cur.close()
    conn.close()


# ------------------------------------------------------------------
# OAuth flow
# ------------------------------------------------------------------
@APP.route("/")
def home():
    tenant_id = request.args.get("tenant_id")
    if not tenant_id:
        return "Missing tenant_id", 400
    return render_wait_page(f"/oauth?tenant_id={tenant_id}")


@APP.route("/start")
def start():
    tenant_id = request.args.get("tenant_id")
    if not tenant_id:
        return "Missing tenant_id", 400
    return render_wait_page(f"/oauth?tenant_id={tenant_id}")


@APP.route("/oauth")
def oauth_start():
    tenant_id = request.args.get("tenant_id")
    if not tenant_id:
        return "Missing tenant_id", 400

    return intuit.authorize_redirect(
        REDIRECT_URI,
        state=tenant_id,
        prompt="consent",
    )


@APP.route("/callback")
def callback():
    code = request.args.get("code")
    realm_id = request.args.get("realmId")
    tenant_id = request.args.get("state")

    if not code or not realm_id or not tenant_id:
        return "Invalid OAuth response", 400

    try:
        response = requests.post(
            TOKEN_URL,
            auth=(CLIENT_ID, CLIENT_SECRET),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
            timeout=10,
        )
        response.raise_for_status()
        token = response.json()

        intuit_email = None
        intuit_user_id = None

        if token.get("access_token"):
            r = requests.get(
                USERINFO_URL,
                headers={"Authorization": f"Bearer {token['access_token']}"},
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                intuit_email = data.get("email")
                intuit_user_id = data.get("sub")

        upsert_qbo_token(
            token=token,
            realm_id=realm_id,
            tenant_id=tenant_id,
            intuit_email=intuit_email,
            intuit_user_id=intuit_user_id,
        )

        upsert_tenant_qbo_mapping(
            tenant_id=tenant_id,
            realm_id=realm_id,
        )

    except Exception:
        APP.logger.exception("OAuth callback failure")
        return "Authentication failed", 500

    return render_wait_page(RETURN_URL)


# ------------------------------------------------------------------
# Local dev only
# ------------------------------------------------------------------
if __name__ == "__main__":
    APP.run(host="127.0.0.1", port=5000, debug=True)