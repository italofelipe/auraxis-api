"""
app/controllers/admin/feature_flags.py — HTTP admin endpoints for feature flags.

All endpoints require a valid JWT (enforced by the global auth guard).
The blueprint is registered with the ``/admin`` URL prefix.

Endpoints
---------
    GET    /admin/feature-flags          → list all flags
    GET    /admin/feature-flags/<name>   → get a single flag
    POST   /admin/feature-flags          → create or update a flag
    DELETE /admin/feature-flags/<name>   → delete a flag
"""

from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from app.services.feature_flag_service import get_feature_flag_service

admin_feature_flags_bp = Blueprint("admin_feature_flags", __name__)


@admin_feature_flags_bp.get("/feature-flags")
def list_feature_flags() -> Response:
    """Return all feature flags stored in Redis."""
    svc = get_feature_flag_service()
    flags = svc.list_flags()
    payload = {name: cfg.to_dict() for name, cfg in flags.items()}
    return jsonify({"flags": payload, "count": len(payload)})


@admin_feature_flags_bp.get("/feature-flags/<string:name>")
def get_feature_flag(name: str) -> Response:
    """Return a single feature flag by name."""
    svc = get_feature_flag_service()
    config = svc.get_flag(name)
    if config is None:
        response = jsonify(
            {
                "message": "Feature flag not found",
                "success": False,
                "error": {"code": "NOT_FOUND", "details": {"name": name}},
            }
        )
        response.status_code = 404
        return response
    return jsonify({"name": name, **config.to_dict()})


@admin_feature_flags_bp.post("/feature-flags")
def create_or_update_feature_flag() -> Response:
    """Create or update a feature flag.

    Expected JSON body:
        {
            "name": "tools.fgts_simulator",
            "enabled": true,
            "canary_percentage": 10,
            "description": "Enables FGTS simulator for canary users"
        }
    """
    body = request.get_json(silent=True) or {}
    name = body.get("name", "")
    if not name or not isinstance(name, str):
        response = jsonify(
            {
                "message": "Field 'name' is required and must be a non-empty string.",
                "success": False,
                "error": {"code": "VALIDATION_ERROR", "details": {"name": "required"}},
            }
        )
        response.status_code = 422
        return response

    enabled = bool(body.get("enabled", True))
    canary_percentage = int(body.get("canary_percentage", 0))
    description = str(body.get("description", ""))

    if not (0 <= canary_percentage <= 100):
        response = jsonify(
            {
                "message": "canary_percentage must be between 0 and 100.",
                "success": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "details": {"canary_percentage": "must be 0-100"},
                },
            }
        )
        response.status_code = 422
        return response

    svc = get_feature_flag_service()
    svc.set_flag(
        name,
        enabled=enabled,
        canary_percentage=canary_percentage,
        description=description,
    )

    config = svc.get_flag(name)
    if config is None:
        response = jsonify(
            {
                "message": "Flag created but Redis may be unavailable.",
                "success": False,
                "error": {"code": "SERVICE_UNAVAILABLE", "details": {}},
            }
        )
        response.status_code = 503
        return response

    response = jsonify({"name": name, **config.to_dict()})
    response.status_code = 201
    return response


@admin_feature_flags_bp.delete("/feature-flags/<string:name>")
def delete_feature_flag(name: str) -> Response:
    """Delete a feature flag by name (immediate kill switch)."""
    svc = get_feature_flag_service()
    svc.delete_flag(name)
    response = jsonify({"message": f"Flag '{name}' deleted.", "success": True})
    response.status_code = 200
    return response


__all__ = ["admin_feature_flags_bp"]
