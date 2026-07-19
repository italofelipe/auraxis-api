"""Contract tests for the OpenAPI-generated Postman collection.

These tests verify that ``scripts/openapi_to_postman.py`` produces a
collection that covers the routes exposed in ``openapi.json``, uses
deterministic folder names, and has unique request names.

Routes NOT in the OpenAPI spec (alerts, subscriptions, shared-entries,
fiscal, GraphQL, tags/accounts/credit-cards) are tracked in
``OPENAPI_GAPS`` and excluded from coverage checks until they are
registered with apispec.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _load_postman_items() -> list[dict[str, object]]:
    collection_path = (
        Path(__file__).resolve().parents[1]
        / "api-tests"
        / "postman"
        / "auraxis.postman_collection.json"
    )
    payload = json.loads(collection_path.read_text())
    items = payload.get("item")
    assert isinstance(items, list)
    return items


def _flatten_request_items(items: list[dict[str, object]]) -> list[dict[str, object]]:
    flattened: list[dict[str, object]] = []
    for item in items:
        nested = item.get("item")
        if isinstance(nested, list):
            flattened.extend(_flatten_request_items(nested))
            continue
        flattened.append(item)
    return flattened


def _normalize_path(raw_url: str) -> str:
    path = raw_url.split("{{baseUrl}}", 1)[1].split("?", 1)[0]
    segments = []
    for segment in path.split("/"):
        if not segment:
            continue
        if segment.startswith(":"):
            segments.append("{param}")
            continue
        if segment.startswith("{{") and segment.endswith("}}"):
            segments.append("{param}")
            continue
        if re.fullmatch(r"\{[^}]+\}", segment):
            segments.append("{param}")
            continue
        segments.append(segment)
    return "/" + "/".join(segments)


# Routes registered in Flask but not yet in the OpenAPI spec.
# Each entry is (METHOD, normalized_path). These are excluded from
# coverage checks until apispec registration is added.
OPENAPI_GAPS: set[tuple[str, str]] = {
    # Alerts
    ("GET", "/alerts"),
    ("GET", "/alerts/preferences"),
    ("PUT", "/alerts/preferences/{param}"),
    ("POST", "/alerts/{param}/read"),
    ("DELETE", "/alerts/{param}"),
    # Subscriptions
    ("GET", "/subscriptions/plans"),
    ("GET", "/subscriptions/me"),
    ("POST", "/subscriptions/checkout"),
    ("POST", "/subscriptions/cancel"),
    ("POST", "/subscriptions/webhook"),
    ("POST", "/subscriptions/webhook/{param}"),
    # Shared entries
    ("POST", "/shared-entries"),
    ("GET", "/shared-entries/by-me"),
    ("GET", "/shared-entries/with-me"),
    ("DELETE", "/shared-entries/{param}"),
    ("PATCH", "/shared-entries/{param}"),
    ("GET", "/shared-entries/invitations"),
    ("POST", "/shared-entries/invitations"),
    ("POST", "/shared-entries/invitations/{param}/accept"),
    ("DELETE", "/shared-entries/invitations/{param}"),
    # Fiscal
    ("POST", "/fiscal/csv/upload"),
    ("POST", "/fiscal/csv/confirm"),
    ("GET", "/fiscal/receivables"),
    ("POST", "/fiscal/receivables"),
    ("PATCH", "/fiscal/receivables/{param}/receive"),
    ("DELETE", "/fiscal/receivables/{param}"),
    ("GET", "/fiscal/receivables/summary"),
    ("GET", "/fiscal/fiscal-documents"),
    ("POST", "/fiscal/fiscal-documents"),
    # Tags, accounts, credit cards
    ("GET", "/tags"),
    ("POST", "/tags"),
    ("GET", "/tags/{param}"),
    ("PATCH", "/tags/{param}"),
    ("DELETE", "/tags/{param}"),
    ("GET", "/accounts"),
    ("POST", "/accounts"),
    ("GET", "/accounts/{param}"),
    ("PATCH", "/accounts/{param}"),
    ("DELETE", "/accounts/{param}"),
    ("GET", "/credit-cards"),
    ("POST", "/credit-cards"),
    ("GET", "/credit-cards/{param}"),
    ("PATCH", "/credit-cards/{param}"),
    ("DELETE", "/credit-cards/{param}"),
    ("GET", "/credit-cards/{param}/bill"),
    ("GET", "/credit-cards/{param}/utilization"),
    # GraphQL
    ("GET", "/graphql"),
    ("POST", "/graphql"),
    # GraphiQL playground — admin-only HTML UI, not a REST API contract
    ("GET", "/graphql/playground"),
    # Reminders CLI-only (no REST route)
    # Auth email routes (confirm/resend have REST but via different path convention)
    # Recurrence
    ("GET", "/recurrences"),
    ("POST", "/recurrences"),
    ("GET", "/recurrences/{param}"),
    ("PATCH", "/recurrences/{param}"),
    ("DELETE", "/recurrences/{param}"),
    ("POST", "/recurrences/{param}/execute"),
    # Webhook events
    ("GET", "/webhook-events"),
    ("POST", "/webhook-events"),
    ("GET", "/webhook-events/{param}"),
    ("PATCH", "/webhook-events/{param}"),
    ("DELETE", "/webhook-events/{param}"),
    # J-task routes (MVP2)
    ("GET", "/j-tasks"),
    ("POST", "/j-tasks"),
    ("GET", "/j-tasks/{param}"),
    ("PATCH", "/j-tasks/{param}"),
    ("DELETE", "/j-tasks/{param}"),
    ("POST", "/j-tasks/{param}/execute"),
    # PUT variants (some resources expose PUT alongside PATCH)
    ("PUT", "/accounts/{param}"),
    ("PUT", "/credit-cards/{param}"),
    ("PUT", "/tags/{param}"),
    # Admin feature flags
    ("GET", "/admin/feature-flags"),
    ("POST", "/admin/feature-flags"),
    ("GET", "/admin/feature-flags/{param}"),
    ("DELETE", "/admin/feature-flags/{param}"),
    # Admin audit trail (#1052)
    ("GET", "/admin/audit-trail/{param}/{param}"),
    # Admin AI Insight audit preview (#1311)
    ("POST", "/admin/ai-insights/preview"),
    # Bank statements
    ("POST", "/bank-statements/preview"),
    ("POST", "/bank-statements/confirm"),
    # Advisory (not yet in apispec-documented blueprints)
    ("GET", "/advisory/insights"),
    # Dashboard routes not yet in apispec-documented blueprints
    ("GET", "/dashboard/survival-index"),
    ("GET", "/dashboard/weekly-summary"),
    # Multi-device session management (#1028)
    ("GET", "/auth/sessions"),
    ("DELETE", "/auth/sessions"),
    ("DELETE", "/auth/sessions/{param}"),
}


def test_postman_collection_uses_domain_folders() -> None:
    """Verify folder structure matches the OpenAPI tag mapping."""
    top_level = _load_postman_items()
    folder_names = [str(item.get("name")) for item in top_level]
    expected = [
        "00 - Health",
        "01 - Auth",
        "02 - User",
        "03 - Transactions",
        "04 - Budgets",
        "05 - Goals",
        "06 - Wallet",
        "07 - Simulations",
        "08 - Entitlements",
        "09 - Notifications",
        "10 - LGPD",
        "11 - AI Advisory",
        "99 - Cleanup",
    ]
    assert folder_names == expected


def test_postman_collection_request_names_are_unique() -> None:
    items = _flatten_request_items(_load_postman_items())
    names = [str(item.get("name")) for item in items]
    assert len(names) == len(set(names)), "Postman request names must stay unique"


def test_postman_collection_covers_openapi_paths() -> None:
    """Every path in openapi.json must have a corresponding Postman request."""
    openapi_path = Path(__file__).resolve().parents[1] / "openapi.json"
    spec = json.loads(openapi_path.read_text())
    covered = {
        (
            str(item["request"]["method"]).upper(),
            _normalize_path(str(item["request"]["url"]["raw"])),
        )
        for item in _flatten_request_items(_load_postman_items())
    }

    missing = []
    for path, methods in spec.get("paths", {}).items():
        for method in methods:
            if method.upper() == "OPTIONS":
                continue
            if not isinstance(methods[method], dict):
                continue
            normalized = re.sub(r"\{[^}]+\}", "{param}", path)
            key = (method.upper(), normalized)
            if key not in covered:
                missing.append(key)

    assert not missing, f"Postman collection missing OpenAPI paths: {sorted(missing)}"


def test_postman_collection_covers_registered_rest_routes(app: Any) -> None:
    """Check coverage of registered Flask routes, excluding known OpenAPI gaps."""
    covered = {
        (
            str(item["request"]["method"]).upper(),
            _normalize_path(str(item["request"]["url"]["raw"])),
        )
        for item in _flatten_request_items(_load_postman_items())
    }
    missing: list[tuple[str, str, str]] = []

    with app.app_context():
        for rule in sorted(
            app.url_map.iter_rules(),
            key=lambda r: (r.rule, sorted(r.methods)),
        ):
            if rule.endpoint == "static" or rule.endpoint.startswith("flask-apispec."):
                continue
            if rule.rule.startswith("/docs") or rule.rule.startswith("/swagger"):
                continue
            normalized_rule = re.sub(r"<(?:[^:>]+:)?[^>]+>", "{param}", rule.rule)
            for method in sorted(
                m for m in rule.methods if m not in {"HEAD", "OPTIONS"}
            ):
                route_key = (method, normalized_rule)
                if route_key in OPENAPI_GAPS:
                    continue
                if route_key not in covered:
                    missing.append((method, normalized_rule, rule.endpoint))

    assert not missing, f"Postman collection missing registered REST routes: {missing}"


def test_postman_collection_has_auth_headers_for_protected_routes() -> None:
    """Protected endpoints must include Authorization header."""
    public_prefixes = {
        "/healthz",
        "/readiness",
        "/ops/",
        "/auth/login",
        "/auth/register",
        "/auth/password/",
        "/auth/email/",
        "/simulations/installment-vs-cash/calculate",
    }
    items = _flatten_request_items(_load_postman_items())
    missing_auth = []
    for item in items:
        request = item.get("request", {})
        raw_url = str(request.get("url", {}).get("raw", ""))
        path = raw_url.split("{{baseUrl}}", 1)[-1].split("?")[0]
        if any(path.startswith(p) for p in public_prefixes):
            continue
        headers = request.get("header", [])
        has_auth = any(h.get("key") == "Authorization" for h in headers)
        if not has_auth:
            missing_auth.append(item.get("name"))
    assert not missing_auth, (
        f"Protected routes missing Authorization header: {missing_auth}"
    )


# ---------------------------------------------------------------------------
# Semantic contract tests — catch runtime failures at build time
# ---------------------------------------------------------------------------


def test_postman_post_put_patch_have_content_type() -> None:
    """POST/PUT/PATCH must always include a Content-Type header.

    Flask returns 415 Unsupported Media Type when Content-Type is missing.
    Accepted values: application/json (JSON body) or multipart/form-data (file upload).
    """
    _ACCEPTED = {"application/json", "multipart/form-data"}
    items = _flatten_request_items(_load_postman_items())
    missing: list[str] = []
    for item in items:
        req = item.get("request", {})
        method = str(req.get("method", "")).upper()
        if method not in ("POST", "PUT", "PATCH"):
            continue
        headers = req.get("header", [])
        has_ct = any(
            h.get("key") == "Content-Type" and h.get("value") in _ACCEPTED
            for h in headers
        )
        if not has_ct:
            missing.append(f"{method} {item.get('name')}")
    assert not missing, (
        f"POST/PUT/PATCH requests missing Content-Type header: {missing}"
    )


def test_postman_required_query_params_present() -> None:
    """Endpoints with required query params in OpenAPI must be present."""
    openapi_path = Path(__file__).resolve().parents[1] / "openapi.json"
    spec = json.loads(openapi_path.read_text())

    # Build map: (METHOD, normalized_path) -> [required_param_names]
    required_params: dict[tuple[str, str], list[str]] = {}
    for path, methods in spec.get("paths", {}).items():
        for method, op in methods.items():
            if not isinstance(op, dict) or method.upper() == "OPTIONS":
                continue
            rq = [
                p["name"]
                for p in op.get("parameters", [])
                if p.get("in") == "query" and p.get("required")
            ]
            if rq:
                normalized = re.sub(r"\{[^}]+\}", "{param}", path)
                required_params[(method.upper(), normalized)] = rq

    items = _flatten_request_items(_load_postman_items())
    missing: list[str] = []
    for item in items:
        req = item.get("request", {})
        method = str(req.get("method", "")).upper()
        raw_url = str(req.get("url", {}).get("raw", ""))
        norm_path = _normalize_path(raw_url)
        key = (method, norm_path)
        if key not in required_params:
            continue
        query = req.get("url", {}).get("query", [])
        present_keys = {str(q.get("key", "")) for q in query}
        for param_name in required_params[key]:
            if param_name not in present_keys:
                missing.append(f"{method} {norm_path} missing ?{param_name}")
    assert not missing, (
        f"Requests missing required query params from OpenAPI spec: {missing}"
    )


def test_postman_id_capture_for_dependent_operations() -> None:
    """Create endpoints (POST) that produce IDs used by later requests must
    capture them in test scripts via pm.collectionVariables.set().

    This catches the common bug where a POST creates a resource but
    subsequent GET/PATCH/PUT/DELETE fail with 404 because the ID
    was never captured.
    """
    items = _flatten_request_items(_load_postman_items())

    # Build set of collection variables used in path segments
    path_vars_used: set[str] = set()
    for item in items:
        req = item.get("request", {})
        raw_url = str(req.get("url", {}).get("raw", ""))
        # Match {{varName}} in path (not query)
        path_part = raw_url.split("?")[0]
        for match in re.finditer(r"\{\{(\w+)\}\}", path_part):
            var = match.group(1)
            if var != "baseUrl":
                path_vars_used.add(var)

    # Check that each used variable is set somewhere in test scripts
    all_test_code = ""
    for item in items:
        for event in item.get("event", []):
            if event.get("listen") == "test":
                lines = event.get("script", {}).get("exec", [])
                all_test_code += "\n".join(lines)

    missing: list[str] = []
    for var in sorted(path_vars_used):
        # Must appear in a pm.collectionVariables.set('varName', ...) call
        pattern = f"pm.collectionVariables.set('{var}'"
        if pattern not in all_test_code:
            # Also check double-quote variant
            pattern_dq = f'pm.collectionVariables.set("{var}"'
            if pattern_dq not in all_test_code:
                missing.append(var)

    assert not missing, (
        f"Path variables used in URLs but never captured in test scripts: {missing}. "
        f"A POST endpoint must set these via pm.collectionVariables.set()."
    )


def test_postman_collection_is_up_to_date() -> None:
    """The committed collection must match what the generator produces.

    Prevents pushing a hand-edited collection that diverges from the
    generator, which would cause CI to behave differently than
    local regeneration.
    """
    from scripts.openapi_to_postman import (
        COLLECTION_PATH,
        OPENAPI_PATH,
        build_collection,
    )

    spec = json.loads(OPENAPI_PATH.read_text())
    expected = build_collection(spec)
    actual = json.loads(COLLECTION_PATH.read_text())

    assert actual == expected, (
        "Postman collection is stale — run 'python3 scripts/openapi_to_postman.py' "
        "to regenerate. The committed collection must match the generator output."
    )


def test_custom_validation_endpoints_have_enrichment() -> None:
    """INI-3: Endpoints using @validates_schema must have test_lines in ENRICHMENT.

    When a Marshmallow schema uses @validates_schema, the auto-generated body
    from OpenAPI will not pass custom validation in Newman smoke tests.
    Each such endpoint must have a test_lines override in ENRICHMENT that
    accepts the expected failure codes (e.g., 400, 404).

    To add a new endpoint: update CUSTOM_VALIDATION_ENDPOINTS in
    scripts/openapi_to_postman.py AND add an ENRICHMENT test_lines entry.
    See: docs/wiki/Post-Mortem-PR1174-Bootstrap-Migration.md (INI-3)
    """
    from scripts.openapi_to_postman import CUSTOM_VALIDATION_ENDPOINTS, ENRICHMENT

    missing_enrichment: list[str] = []
    for operation in sorted(CUSTOM_VALIDATION_ENDPOINTS):
        entry = ENRICHMENT.get(operation, {})
        if not entry.get("test_lines"):
            missing_enrichment.append(operation)

    assert not missing_enrichment, (
        "Endpoints with @validates_schema missing ENRICHMENT test_lines override:\n"
        + "\n".join(f"  - {op}" for op in missing_enrichment)
        + "\n\nAdd test_lines to ENRICHMENT in scripts/openapi_to_postman.py "
        "so Newman smoke tests accept validation failures gracefully."
    )
