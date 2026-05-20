"""Human-readable client_request.comment for UI (strip pass/certificate order markers)."""
from __future__ import annotations

from src.application.client_cert_order_use_cases import split_cert_order_comment
from src.application.client_pass_order_use_cases import split_pass_order_comment


def client_visible_request_comment(comment: str | None) -> str | None:
    """
    Comment text safe to show the client in «Мои заявки».
    Pass/certificate orders store machine prefixes in DB; trainers still get full comment.
    """
    if not comment or not str(comment).strip():
        return None
    raw = str(comment).strip()
    pid, body_pass = split_pass_order_comment(comment)
    if pid is not None:
        if body_pass.strip() == raw:
            return None
        return body_pass.strip() or None
    cid, _meta, body_cert = split_cert_order_comment(comment)
    if cid is not None:
        if body_cert.strip() == raw:
            return None
        return body_cert.strip() or None
    return raw or None


def client_request_subtype(comment: str | None) -> str | None:
    """pass_product_order | certificate_product_order | None (ordinary demand request)."""
    pid, _ = split_pass_order_comment(comment)
    if pid is not None:
        return "pass_product_order"
    cid, _, _ = split_cert_order_comment(comment)
    if cid is not None:
        return "certificate_product_order"
    return None


def client_request_comment_editable(comment: str | None) -> bool:
    """Pass/certificate orders embed machine markers — editing would drop order type."""
    return client_request_subtype(comment) is None
