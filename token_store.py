from datetime import datetime, timedelta
from db import get_db_conn

def upsert_qbo_token(
    token: dict,
    realm_id: str,
    tenant_id: str,
    environment: str,
    client_id: str,
    intuit_email: str = None,
    intuit_user_id: str = None,
):
    issued_at = datetime.utcnow()

    access_expires_at = issued_at + timedelta(
        seconds=int(token.get("expires_in", 3600))
    )

    refresh_expires_at = issued_at + timedelta(
        seconds=int(token.get("x_refresh_token_expires_in", 0))
    )

    sql = """
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
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())
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
        updated_at = NOW();
    """

    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute(
        sql,
        (
            tenant_id,
            realm_id,
            intuit_user_id,
            intuit_email,
            token["access_token"],
            token["refresh_token"],
            token.get("token_type", "bearer"),
            token.get("expires_in"),
            token.get("x_refresh_token_expires_in"),
            issued_at,
            access_expires_at,
            refresh_expires_at,
            environment,
            client_id,
        ),
    )
    conn.commit()
    cur.close()
    conn.close()