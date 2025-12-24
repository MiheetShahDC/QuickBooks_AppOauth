from datetime import datetime, timedelta
from db import get_db_conn

def upsert_qbo_token(token: dict, realm_id: str, environment: str, client_id: str):
    issued_at = datetime.utcnow()

    access_expires_at = issued_at + timedelta(
        seconds=int(token.get("expires_in", 3600))
    )

    refresh_expires_at = issued_at + timedelta(
        seconds=int(token.get("x_refresh_token_expires_in", 0))
    )

    sql = """
    INSERT INTO config.qbo_oauth_tokens (
        realm_id,
        access_token,
        refresh_token,
        token_type,
        expires_in,
        issued_at_utc,
        access_token_expires_at,
        refresh_token_expires_at,
        qbo_environment,
        client_id,
        created_at,
        updated_at
    )
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())
    ON CONFLICT (realm_id, qbo_environment)
    DO UPDATE SET
        access_token = EXCLUDED.access_token,
        refresh_token = EXCLUDED.refresh_token,
        expires_in = EXCLUDED.expires_in,
        issued_at_utc = EXCLUDED.issued_at_utc,
        access_token_expires_at = EXCLUDED.access_token_expires_at,
        refresh_token_expires_at = EXCLUDED.refresh_token_expires_at,
        updated_at = NOW();
    """

    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute(sql, (
        realm_id,
        token["access_token"],
        token["refresh_token"],
        token.get("token_type", "bearer"),
        token.get("expires_in"),
        issued_at,
        access_expires_at,
        refresh_expires_at,
        environment,
        client_id
    ))
    conn.commit()
    cur.close()
    conn.close()
