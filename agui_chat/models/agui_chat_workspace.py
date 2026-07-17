# -*- coding: utf-8 -*-
import base64
import hashlib
import hmac
import json
import time
import uuid

from odoo.exceptions import ValidationError


CAPABILITY_AUDIENCE = "agui-agentos-workspace"
CAPABILITY_TTL_SECONDS = 10 * 60
WORKSPACE_SECRET_PARAM = "agui_chat.workspace_hmac_secret"


def _b64encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value):
    value = value.encode("ascii")
    return base64.urlsafe_b64decode(value + b"=" * (-len(value) % 4))


def _json(value):
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")


def workspace_secret(env):
    secret = env["ir.config_parameter"].sudo().get_param(WORKSPACE_SECRET_PARAM)
    if not secret or len(secret.encode("utf-8")) < 32:
        raise ValidationError("工作区 HMAC 密钥未配置或少于 32 字节。")
    return secret


def issue_workspace_capability(env, session, odoo_session, now=None):
    session.ensure_one()
    issued_at = int(time.time() if now is None else now)
    expires_at = issued_at + CAPABILITY_TTL_SECONDS
    claims = {
        "aud": CAPABILITY_AUDIENCE,
        "database": env.cr.dbname,
        "user": env.user.id,
        "company": env.user.company_id.id,
        "odoo_session": hashlib.sha256(
            str(odoo_session or "").encode("utf-8")
        ).hexdigest(),
        "thread": session.thread_id,
        "iat": issued_at,
        "exp": expires_at,
        "jti": str(uuid.uuid4()),
    }
    header = {"alg": "HS256", "typ": "AGUI-CAP"}
    signing_input = "%s.%s" % (_b64encode(_json(header)), _b64encode(_json(claims)))
    signature = hmac.new(
        workspace_secret(env).encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return "%s.%s" % (signing_input, _b64encode(signature)), claims


def decode_workspace_capability(token, secret, now=None):
    try:
        header_value, claims_value, signature_value = str(token or "").split(".")
        signing_input = "%s.%s" % (header_value, claims_value)
        expected = hmac.new(
            secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(expected, _b64decode(signature_value)):
            raise ValueError("capability_signature_invalid")
        header = json.loads(_b64decode(header_value).decode("utf-8"))
        claims = json.loads(_b64decode(claims_value).decode("utf-8"))
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        raise ValueError("capability_invalid")
    current = int(time.time() if now is None else now)
    if header != {"alg": "HS256", "typ": "AGUI-CAP"}:
        raise ValueError("capability_header_invalid")
    if claims.get("aud") != CAPABILITY_AUDIENCE:
        raise ValueError("capability_audience_invalid")
    if not isinstance(claims.get("exp"), int) or claims["exp"] <= current:
        raise ValueError("capability_expired")
    return claims
