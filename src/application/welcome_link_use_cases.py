"""
One-time welcome link tokens. Create token → put in link; client opens → consume token (burn), run flow.
"""
import uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

WELCOME_TOKEN_TYPE_CERT = "cert"
WELCOME_TOKEN_TYPE_PASS = "pass"
WELCOME_TOKEN_TYPE_GENERIC = "generic"
WELCOME_TOKEN_TYPE_CLIENT_BIND = "client_bind"
WELCOME_TOKEN_TYPE_FAMILY_ACCESS = "family_access"


async def create_welcome_link_token(
    session: AsyncSession,
    token_type: str,
    trainer_id: int,
    *,
    cert_code: str | None = None,
    pass_product_id: int | None = None,
    service_id: int | None = None,
    client_id: int | None = None,
) -> uuid.UUID:
    """
    Create a one-time token for a welcome link. Returns token id (UUID) to embed in link.
    type: cert | pass | generic | client_bind. For cert pass cert_code; for pass pass pass_product_id.
    For generic, optional service_id pins catalog/service prefill when trainer has several services.
    For client_bind, pass client_id (Telegram attached on first open to that row).
    """
    token_id = uuid.uuid4()
    await session.execute(
        text("""
            INSERT INTO welcome_link_tokens (
                id, type, trainer_id, cert_code, pass_product_id, service_id, client_id
            )
            VALUES (
                :id, :type, :trainer_id, :cert_code, :pass_product_id, :service_id, :client_id
            )
        """),
        {
            "id": token_id,
            "type": token_type,
            "trainer_id": trainer_id,
            "cert_code": cert_code,
            "pass_product_id": pass_product_id,
            "service_id": service_id,
            "client_id": client_id,
        },
    )
    await session.commit()
    return token_id


async def consume_welcome_link_token(
    session: AsyncSession,
    token_id: uuid.UUID,
) -> dict | None:
    """
    Consume (burn) token if not yet used. Returns payload dict: type, trainer_id, cert_code?,
    pass_product_id?, service_id?.
    Returns None if token invalid or already used.
    """
    r = await session.execute(
        text("""
            UPDATE welcome_link_tokens
            SET used_at = now()
            WHERE id = :id AND used_at IS NULL
            RETURNING type, trainer_id, cert_code, pass_product_id, service_id, client_id
        """),
        {"id": token_id},
    )
    row = r.fetchone()
    await session.commit()
    if not row:
        return None
    return {
        "type": row[0],
        "trainer_id": row[1],
        "cert_code": (row[2] or "").strip() or None,
        "pass_product_id": row[3],
        "service_id": row[4],
        "client_id": row[5],
    }
