"""
Health endpoints.

Why this exists
- Infra (Docker, reverse proxy, load balancers, canaries) needs a stable and
  public liveness endpoint that does not require authentication.
- We intentionally keep this lightweight (no DB check by default) to avoid
  cascading failures during partial outages.

Contract
- `GET /healthz` returns HTTP 200 with a minimal JSON body.
- `GET /readiness` returns 200 when DB and Redis are reachable, 503 otherwise.
  Protected by a bearer token (READINESS_TOKEN env var). Each dependency
  is checked with a 3-second timeout and reports "ok" or "error" individually.
"""

from __future__ import annotations

import importlib
import os
from typing import Literal

from flask import Blueprint, request
from sqlalchemy import text

from app.extensions.database import db
from app.utils.typed_decorators import typed_doc as doc

health_bp = Blueprint("health", __name__)

_READINESS_CHECK_TIMEOUT_SECONDS = 3

DependencyStatus = Literal["ok", "error"]


def _check_db() -> DependencyStatus:
    """Probe the database by executing a lightweight SELECT 1."""
    try:
        db.session.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "error"


def _check_redis() -> DependencyStatus:
    """Probe Redis via the URL configured for rate-limiting or login-guard."""
    redis_url = (
        os.getenv("RATE_LIMIT_REDIS_URL")
        or os.getenv("LOGIN_GUARD_REDIS_URL")
        or os.getenv("REDIS_URL")
        or ""
    ).strip()

    if not redis_url:
        # No Redis configured — treat as healthy (Redis is optional in dev/test).
        return "ok"

    try:
        redis_mod = importlib.import_module("redis")
        client = redis_mod.Redis.from_url(
            redis_url,
            socket_connect_timeout=_READINESS_CHECK_TIMEOUT_SECONDS,
            socket_timeout=_READINESS_CHECK_TIMEOUT_SECONDS,
        )
        client.ping()
        return "ok"
    except Exception:
        return "error"


def _is_authorized_readiness_request() -> bool:
    """
    Verify the request carries the expected internal bearer token.

    When READINESS_TOKEN is not configured the endpoint is open to any caller
    (permissive default so infra probes work without extra config in dev).
    """
    expected_token = os.getenv("READINESS_TOKEN", "").strip()
    if not expected_token:
        return True

    auth_header = request.headers.get("Authorization", "").strip()
    if not auth_header.lower().startswith("bearer "):
        return False

    provided_token = auth_header.split(" ", 1)[1].strip()
    # Constant-time comparison to prevent timing attacks.
    return _secure_compare(provided_token, expected_token)


def _secure_compare(a: str, b: str) -> bool:
    """Constant-time string comparison."""
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a.encode(), b.encode(), strict=True):
        result |= x ^ y
    return result == 0


@health_bp.get("/healthz")
@doc(
    description="Endpoint público de liveness para probes de infraestrutura.",
    tags=["Health"],
    responses={200: {"description": "Serviço saudável"}},
)
def healthz() -> tuple[dict[str, str], int]:
    """Liveness probe endpoint (public).

    Expõe o ``commit`` (SHA gravado no build via AURAXIS_COMMIT_SHA) para
    detecção externa de drift/rollback de imagem sem SSH — o gate de deploy e o
    ``verify-prod-state`` comparam com o SHA esperado. "unknown" em builds sem o
    build-arg (dev/local).
    """

    return {
        "status": "ok",
        "commit": os.getenv("AURAXIS_COMMIT_SHA", "unknown"),
    }, 200


@health_bp.get("/readiness")
@doc(
    description=(
        "Readiness probe: verifica se DB e Redis estão acessíveis. "
        "Retorna 200 quando tudo está ok, 503 quando alguma dependência falhou. "
        "Protegido por bearer token (READINESS_TOKEN) quando configurado."
    ),
    tags=["Health"],
    responses={
        200: {"description": "Todas as dependências saudáveis"},
        401: {"description": "Token de autorização ausente ou inválido"},
        503: {"description": "Uma ou mais dependências indisponíveis"},
    },
)
def readiness() -> tuple[dict[str, str], int]:
    """Readiness probe — checks DB and Redis reachability (internal use)."""

    if not _is_authorized_readiness_request():
        return {"error": "Unauthorized"}, 401

    db_status: DependencyStatus = _check_db()
    redis_status: DependencyStatus = _check_redis()

    overall_status: Literal["ready", "degraded"] = (
        "ready" if db_status == "ok" and redis_status == "ok" else "degraded"
    )
    http_status = 200 if overall_status == "ready" else 503

    return (
        {
            "db": db_status,
            "redis": redis_status,
            "status": overall_status,
        },
        http_status,
    )
