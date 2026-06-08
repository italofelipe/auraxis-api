#!/usr/bin/env python3
# ruff: noqa: E501, C901
"""POSTMAN-02 — Generate a Postman Collection v2.1 from openapi.json.

Reads the committed ``openapi.json`` (produced by ``flask openapi-export``)
and outputs a deterministic Postman collection at
``api-tests/postman/auraxis.postman_collection.json``.

Tag → folder mapping, auth headers, suite-profile skip logic, and basic
status-code assertions are applied automatically.  The enrichment config
in ``ENRICHMENT`` lets us attach custom pre-request / test scripts and
example bodies for specific operations.

Usage:
    python3 scripts/openapi_to_postman.py
    # or via npm:
    npm run postman:build
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = ROOT / "openapi.json"
COLLECTION_PATH = ROOT / "api-tests" / "postman" / "auraxis.postman_collection.json"

# ---------------------------------------------------------------------------
# Tag → numbered folder mapping (matches existing README structure)
# ---------------------------------------------------------------------------
TAG_FOLDER_MAP: dict[str, str] = {
    "Health": "00 - Health",
    "Observability": "00 - Health",
    "Autenticação": "01 - Auth",
    "Usuário": "02 - User",
    "Transações": "03 - Transactions",
    "Dashboard": "03 - Transactions",
    "Orçamentos": "04 - Budgets",
    "Metas": "05 - Goals",
    "Wallet": "06 - Wallet",
    "Simulações": "07 - Simulations",
    "Entitlements": "08 - Entitlements",
    "Notificações": "09 - Notifications",
    "LGPD": "10 - LGPD",
    "AI Advisory": "11 - AI Advisory",
}
DEFAULT_FOLDER = "99 - Other"

# Per-operation folder override — takes precedence over tag and path-prefix mapping.
# Use this to relocate specific operations (e.g. logout to the end of the run).
OPERATION_FOLDER_OVERRIDE: dict[str, str] = {
    "POST /auth/logout": "99 - Cleanup",
}

# Path-prefix fallback for untagged endpoints
PATH_FOLDER_FALLBACK: dict[str, str] = {
    "/goals": "05 - Goals",
    "/simulations": "07 - Simulations",
    "/budgets": "04 - Budgets",
    "/transactions": "03 - Transactions",
    "/wallet": "06 - Wallet",
    "/auth": "01 - Auth",
    "/user": "02 - User",
}

# Explicit operation ordering within folders.
# Operations listed here are placed first (in given order);
# remaining operations sort alphabetically after them.
OPERATION_ORDER: dict[str, list[str]] = {
    "01 - Auth": [
        "POST /auth/register",
        "POST /auth/login",
        "POST /auth/refresh",
        "GET /user/me",
    ],
    "02 - User": [
        "GET /user/me",
        "GET /user/bootstrap",
        "GET /user/profile",
        "PUT /user/profile",
        "GET /user/notification-preferences",
        "PATCH /user/notification-preferences",
        "GET /user/profile/questionnaire",
        "POST /user/profile/questionnaire",
        "POST /user/simulate-salary-increase",
        "DELETE /user/me",
    ],
    "03 - Transactions": [
        "POST /transactions",
        "GET /transactions",
        "GET /transactions/{transaction_id}",
        "PATCH /transactions/{transaction_id}",
        "PUT /transactions/{transaction_id}",
        "GET /transactions/summary",
        "GET /dashboard/overview",
        "GET /dashboard/trends",
        "GET /transactions/dashboard",
        "GET /transactions/expenses",
        "GET /transactions/due-range",
        "GET /transactions/list",
        "DELETE /transactions/{transaction_id}",
        "GET /transactions/deleted",
        "PATCH /transactions/restore/{transaction_id}",
        "DELETE /transactions/{transaction_id}/force",
    ],
    "04 - Budgets": [
        "POST /budgets",
        "GET /budgets",
        "GET /budgets/{budget_id}",
        "PATCH /budgets/{budget_id}",
        "GET /budgets/summary",
        "DELETE /budgets/{budget_id}",
    ],
    "05 - Goals": [
        "POST /goals",
        "GET /goals",
        "GET /goals/{goal_id}",
        "PATCH /goals/{goal_id}",
        "PUT /goals/{goal_id}",
        "GET /goals/{goal_id}/plan",
        "GET /goals/{goal_id}/projection",
        "POST /goals/simulate",
        "DELETE /goals/{goal_id}",
    ],
    "06 - Wallet": [
        "POST /wallet",
        "GET /wallet",
        "GET /wallet/{investment_id}",
        "PATCH /wallet/{investment_id}",
        "PUT /wallet/{investment_id}",
        "GET /wallet/valuation",
        "GET /wallet/{investment_id}/valuation",
        "GET /wallet/valuation/history",
        "GET /wallet/{investment_id}/history",
        "POST /wallet/{investment_id}/operations",
        "GET /wallet/{investment_id}/operations",
        "GET /wallet/{investment_id}/operations/invested-amount",
        "GET /wallet/{investment_id}/operations/position",
        "GET /wallet/{investment_id}/operations/summary",
        "PUT /wallet/{investment_id}/operations/{operation_id}",
        "DELETE /wallet/{investment_id}/operations/{operation_id}",
        "DELETE /wallet/{investment_id}",
    ],
    "07 - Simulations": [
        "POST /simulations",
        "GET /simulations",
        "GET /simulations/{simulation_id}",
        "POST /simulations/installment-vs-cash/calculate",
        "POST /simulations/installment-vs-cash",
        "POST /simulations/installment-vs-cash/save",
        "POST /simulations/{simulation_id}/goal",
        "POST /simulations/{simulation_id}/planned-expense",
        "DELETE /simulations/{simulation_id}",
    ],
}

# Folder ordering for deterministic output
FOLDER_ORDER = [
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
    "99 - Other",
]

# ---------------------------------------------------------------------------
# Public / no-auth endpoints (by path prefix)
# ---------------------------------------------------------------------------
PUBLIC_PATHS = {
    "/healthz",
    "/readiness",
    "/ops/metrics",
    "/ops/observability",
    "/auth/login",
    "/auth/register",
    "/auth/password/forgot",
    "/auth/password/reset",
    "/auth/email/confirm",
    "/auth/email/resend",
    "/simulations/installment-vs-cash/calculate",
}

# ---------------------------------------------------------------------------
# INI-3: Endpoints that use Marshmallow @validates_schema (custom validation).
# The auto-generated body from OpenAPI schema will NOT pass this validation
# in CI smoke tests — these endpoints MUST have test_lines override in ENRICHMENT.
#
# Update this set whenever a new endpoint uses @validates_schema.
# The test_postman_collection_contract.py::test_custom_validation_endpoints_have_enrichment
# test will fail if any entry here lacks test_lines in ENRICHMENT.
# ---------------------------------------------------------------------------
CUSTOM_VALIDATION_ENDPOINTS: set[str] = {
    # push_subscription_schema.py — validates transport + endpoint format per type
    "POST /notifications/subscribe",
    "POST /notifications/unsubscribe",
    # avatar — requires real file + S3; body cannot be auto-generated
    "POST /user/me/avatar",
    "DELETE /user/me/avatar",
    # installment_vs_cash_schema.py — complex cross-field validation
    "POST /simulations/installment-vs-cash",
    "POST /simulations/installment-vs-cash/save",
    # wallet_schema.py — validates quantity/rate conditionally by asset_class
    "POST /wallet",
    "PATCH /wallet/{investment_id}",
    "PUT /wallet/{investment_id}",
    # goal_schema.py GoalContributionInputSchema — @validates amount (non-zero)
    # and occurred_at (no future dates); auto-body fails these.
    "POST /goals/{goal_id}/contributions",
}

# ---------------------------------------------------------------------------
# Suite profile lists — which requests belong to smoke / privileged
# ---------------------------------------------------------------------------
SMOKE_OPERATIONS: set[str] = {
    "GET /healthz",
    "POST /auth/register",
    "POST /auth/login",
    "GET /user/me",
    "GET /user/bootstrap",
    "POST /transactions",
    "GET /transactions",
    "GET /transactions/summary",
    "GET /dashboard/overview",
    "POST /goals",
    "GET /goals",
    "POST /goals/simulate",
    "POST /wallet",
    "GET /wallet",
    "GET /wallet/valuation",
    "POST /simulations/installment-vs-cash/calculate",
    "GET /entitlements",
    "GET /budgets",
    "POST /budgets",
}

PRIVILEGED_OPERATIONS: set[str] = {
    "POST /entitlements/admin",
    "DELETE /entitlements/admin/{entitlement_id}",
    # The session-revocation endpoints invalidate the bearer token mid-run
    # (which breaks every subsequent assertion in the suite). Keep them in
    # the privileged profile so the full smoke run leaves them out.
    "DELETE /auth/sessions",
    "DELETE /auth/sessions/{session_id}",
    # LGPD account deletion irreversibly anonymises the suite user and
    # invalidates the bearer token — same reasoning as the session-revoke
    # endpoints above. (#1257)
    "DELETE /user/me",
}

# ---------------------------------------------------------------------------
# Enrichment config — custom bodies, pre-request, test scripts per operation
# ---------------------------------------------------------------------------
ENRICHMENT: dict[str, dict[str, Any]] = {
    # ── Auth ──────────────────────────────────────────────────────────
    "POST /auth/register": {
        "body_override": json.dumps(
            {
                "name": "{{runName}}",
                "email": "{{runEmail}}",
                "password": "{{testPassword}}",
            },
            indent=2,
        ),
        "test_lines": [
            "pm.test('Register returns 201', function () {",
            "  pm.response.to.have.status(201);",
            "});",
            "var json = pm.response.json();",
            "if (json.data && json.data.user) {",
            "  pm.collectionVariables.set('userId', json.data.user.id);",
            "}",
        ],
    },
    "POST /auth/login": {
        "body_override": json.dumps(
            {
                "email": "{{runEmail}}",
                "password": "{{testPassword}}",
            },
            indent=2,
        ),
        "test_lines": [
            "pm.test('Login returns 200', function () {",
            "  pm.response.to.have.status(200);",
            "});",
            "var json = pm.response.json();",
            "if (json.data && json.data.token) {",
            "  pm.collectionVariables.set('authToken', json.data.token);",
            "}",
            "if (json.data && json.data.refresh_token) {",
            "  pm.collectionVariables.set('refreshToken', json.data.refresh_token);",
            "}",
        ],
    },
    "POST /auth/refresh": {
        "no_body": True,
        "prerequest_lines": [
            "// Refresh endpoint uses @jwt_required(refresh=True) —",
            "// it needs the refresh token as the Bearer token, not the access token.",
            "pm.request.headers.upsert({",
            "  key: 'Authorization',",
            "  value: 'Bearer ' + pm.collectionVariables.get('refreshToken')",
            "});",
        ],
        "test_lines": [
            "pm.test('Refresh returns 200', function () {",
            "  pm.response.to.have.status(200);",
            "});",
            "var json = pm.response.json();",
            "if (json.data && json.data.token) {",
            "  pm.collectionVariables.set('authToken', json.data.token);",
            "}",
            "if (json.data && json.data.refresh_token) {",
            "  pm.collectionVariables.set('refreshToken', json.data.refresh_token);",
            "}",
        ],
    },
    "POST /auth/email/confirm": {
        "test_lines": [
            "// Needs a valid confirmation token from email — expect 400 in automated runs",
            "pm.test('Confirm email — expected 400 without token', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 400]);",
            "});",
        ],
    },
    "GET /auth/sessions": {
        "test_lines": [
            "pm.test('GET /auth/sessions — status 200', function () {",
            "  pm.response.to.have.status(200);",
            "});",
        ],
    },
    "DELETE /auth/sessions/{session_id}": {
        # Cleanup — the smoke suite stays inside a single session for the
        # whole run, so we have no specific id to revoke. We feed a fake
        # UUID into the path variable and accept the 404 the API returns
        # for an unknown session — that is the contract being smoked.
        "prerequest_lines": [
            "pm.collectionVariables.set(",
            "  'session_id', '00000000-0000-0000-0000-000000000000',",
            ");",
        ],
        "test_lines": [
            "pm.test('DELETE /auth/sessions/{session_id} — 200 or 404', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 404]);",
            "});",
        ],
    },
    "DELETE /auth/sessions": {
        # Cleanup — explicitly revokes every active session for the user,
        # which is exactly what the suite wants at the end of a run.
        "test_lines": [
            "pm.test('DELETE /auth/sessions — status 200', function () {",
            "  pm.response.to.have.status(200);",
            "});",
        ],
    },
    "POST /auth/password/reset": {
        "test_lines": [
            "// Needs a valid reset token — expect 400 in automated runs",
            "pm.test('Reset password — expected 400 without token', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 400]);",
            "});",
        ],
    },
    "POST /auth/email/resend": {
        "test_lines": [
            "// Needs authenticated session — expect 401 when no auth header sent",
            "pm.test('Resend confirmation — expected 401/200', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 401]);",
            "});",
        ],
    },
    "POST /auth/password/forgot": {
        "body_override": json.dumps(
            {"email": "{{runEmail}}"},
            indent=2,
        ),
    },
    # ── User ──────────────────────────────────────────────────────────
    # LGPD account deletion (#1257). Requires a password body and revokes
    # the bearer token mid-suite — kept in PRIVILEGED_OPERATIONS so the
    # full smoke run leaves it out. Tolerates 401/403 because the
    # auto-generated stub body has no password and email-confirmation
    # gates may also reject it before reaching the LGPD service.
    "DELETE /user/me": {
        "body_override": json.dumps(
            {"password": "{{testPassword}}"},
            indent=2,
        ),
        "test_lines": [
            "pm.test('LGPD delete — expected 200, 401 or 403', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 401, 403]);",
            "});",
            "if (pm.response.code === 200) {",
            "  pm.test('LGPD delete — report has summary keys', function () {",
            "    const body = pm.response.json();",
            "    const data = body.data || body;",
            "    const report = data.report || {};",
            "    pm.expect(report).to.have.property('summary');",
            "    pm.expect(report.summary).to.have.property('deleted');",
            "    pm.expect(report.summary).to.have.property('anonymized');",
            "    pm.expect(report.summary).to.have.property('retained');",
            "    pm.expect(report).to.have.property('retentions');",
            "  });",
            "}",
        ],
    },
    "PATCH /user/notification-preferences": {
        "body_override": json.dumps(
            {"preferences": [{"category": "due_soon", "enabled": False}]},
            indent=2,
        ),
    },
    # ── Transactions ──────────────────────────────────────────────────
    "POST /transactions": {
        "body_override": json.dumps(
            {
                "title": "Conta de luz {{runSeed}}",
                "amount": "150.50",
                "type": "expense",
                "status": "pending",
                "due_date": "{{runTomorrow}}",
            },
            indent=2,
        ),
        "test_lines": [
            "pm.test('Create transaction returns 201', function () {",
            "  pm.response.to.have.status(201);",
            "});",
            "var json = pm.response.json();",
            "// Response nests under data.transaction (list) — take first item",
            "if (json.data && json.data.transaction && json.data.transaction[0]) {",
            "  pm.collectionVariables.set('transactionId', json.data.transaction[0].id);",
            "}",
        ],
    },
    "GET /transactions/summary": {
        "query_params": [{"key": "month", "value": "{{runMonthRef}}"}],
    },
    "GET /dashboard/overview": {
        "query_params": [{"key": "month", "value": "{{runMonthRef}}"}],
    },
    "GET /transactions/expenses": {
        "query_params": [
            {"key": "start_date", "value": "{{runToday}}"},
            {"key": "end_date", "value": "{{runIn30Days}}"},
        ],
    },
    "GET /transactions/due-range": {
        "query_params": [
            {"key": "start_date", "value": "{{runToday}}"},
            {"key": "end_date", "value": "{{runIn30Days}}"},
        ],
    },
    "GET /transactions/dashboard": {
        "query_params": [{"key": "month", "value": "{{runMonthRef}}"}],
    },
    "PATCH /transactions/restore/{transaction_id}": {
        "test_lines": [
            "pm.test('Restaurar transação deletada — status 200', function () {",
            "  pm.response.to.have.status(200);",
            "});",
        ],
    },
    "DELETE /transactions/{transaction_id}/force": {
        "test_lines": [
            "// Force-delete requires deleted=True; after restore the transaction is active",
            "// so 404 is expected when the flow runs restore before force-delete.",
            "pm.test('Force-delete transaction — expected 200 or 404', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 404]);",
            "});",
        ],
    },
    # ── Budgets ───────────────────────────────────────────────────────
    "PATCH /budgets/{budget_id}": {
        "body_override": json.dumps(
            {"name": "Alimentação atualizada {{runSeed}}"},
            indent=2,
        ),
    },
    "POST /budgets": {
        "body_override": json.dumps(
            {
                "name": "Alimentação {{runSeed}}",
                "amount": "500.00",
                "period": "monthly",
            },
            indent=2,
        ),
        "test_lines": [
            "pm.test('Create budget returns 201', function () {",
            "  pm.response.to.have.status(201);",
            "});",
            "var json = pm.response.json();",
            "// Response nests under data.budget",
            "if (json.data && json.data.budget) {",
            "  pm.collectionVariables.set('budgetId', json.data.budget.id);",
            "}",
        ],
    },
    # ── Goals ─────────────────────────────────────────────────────────
    "PATCH /goals/{goal_id}": {
        "body_override": json.dumps(
            {"title": "Meta atualizada {{runSeed}}"},
            indent=2,
        ),
    },
    "PUT /goals/{goal_id}": {
        "body_override": json.dumps(
            {
                "title": "Meta substituída {{runSeed}}",
                "target_amount": "20000.00",
            },
            indent=2,
        ),
    },
    "POST /goals": {
        "body_override": json.dumps(
            {
                "title": "Reserva de emergencia {{runSeed}}",
                "target_amount": "15000.00",
                "current_amount": "2500.00",
                "target_date": "{{runIn365Days}}",
            },
            indent=2,
        ),
        "test_lines": [
            "pm.test('Create goal returns 201', function () {",
            "  pm.response.to.have.status(201);",
            "});",
            "var json = pm.response.json();",
            "// Response nests under data.goal",
            "if (json.data && json.data.goal) {",
            "  pm.collectionVariables.set('goalId', json.data.goal.id);",
            "}",
        ],
    },
    "POST /goals/simulate": {
        "body_override": json.dumps(
            {
                "target_amount": "50000.00",
                "current_amount": "10000.00",
                "monthly_income": "12000.00",
                "monthly_expenses": "7000.00",
                "monthly_contribution": "2000.00",
                "target_date": "{{runIn365Days}}",
            },
            indent=2,
        ),
    },
    "POST /goals/{goal_id}/contributions": {
        "body_override": json.dumps(
            {"amount": "100.00", "note": "smoke {{runSeed}}"},
            indent=2,
        ),
        # Custom @validates (amount non-zero, no future date) + ownership:
        # with a real {{goalId}} and valid body this is 201; tolerate 400/404
        # when the goal var is unset in a partial run.
        "test_lines": [
            "pm.test('Registrar contribuicao — expected 201 or 400 or 404', "
            "function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([201, 400, 404]);",
            "});",
        ],
    },
    "GET /goals/{goal_id}/contributions": {
        "test_lines": [
            "pm.test('Historico de contribuicoes — expected 200 or 404', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 404]);",
            "});",
        ],
    },
    # ── Wallet ────────────────────────────────────────────────────────
    "PATCH /wallet/{investment_id}": {
        "body_override": json.dumps(
            {"name": "Poupança atualizada {{runSeed}}"},
            indent=2,
        ),
        # wallet_schema.py @validates_schema: quantity/rate conditional on asset_class
        "test_lines": [
            "pm.test('Atualizar investimento — expected 200 or 400 or 404', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 400, 404]);",
            "});",
        ],
    },
    "PUT /wallet/{investment_id}": {
        "body_override": json.dumps(
            {
                "name": "Poupança substituída {{runSeed}}",
                "value": 2000.00,
                "register_date": "{{runToday}}",
                "should_be_on_wallet": True,
            },
            indent=2,
        ),
        # wallet_schema.py @validates_schema: quantity/rate conditional on asset_class
        "test_lines": [
            "pm.test('Substituir investimento — expected 200 or 400 or 404', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 400, 404]);",
            "});",
        ],
    },
    "GET /wallet/{investment_id}/operations/invested-amount": {
        "query_params": [{"key": "date", "value": "{{runToday}}"}],
    },
    "PUT /wallet/{investment_id}/operations/{operation_id}": {
        "body_override": json.dumps(
            {
                "operation_type": "buy",
                "quantity": "10",
                "unit_price": "30.00",
                "fees": "0.00",
            },
            indent=2,
        ),
    },
    "POST /wallet": {
        "body_override": json.dumps(
            {
                "name": "Poupança {{runSeed}}",
                "value": 1500.00,
                "register_date": "{{runToday}}",
                "should_be_on_wallet": True,
            },
            indent=2,
        ),
        "test_lines": [
            "pm.test('Create wallet entry returns 201', function () {",
            "  pm.response.to.have.status(201);",
            "});",
            "var json = pm.response.json();",
            "// Response nests under data.investment",
            "if (json.data && json.data.investment) {",
            "  pm.collectionVariables.set('investmentId', json.data.investment.id);",
            "}",
        ],
    },
    "POST /wallet/{investment_id}/operations": {
        "body_override": json.dumps(
            {
                "operation_type": "buy",
                "quantity": "5",
                "unit_price": "28.50",
                "fees": "0.00",
            },
            indent=2,
        ),
        "test_lines": [
            "pm.test('Create wallet operation returns 201', function () {",
            "  pm.response.to.have.status(201);",
            "});",
            "var json = pm.response.json();",
            "if (json.data && json.data.operation) {",
            "  pm.collectionVariables.set('operationId', json.data.operation.id);",
            "}",
        ],
    },
    # ── Simulations ───────────────────────────────────────────────────
    "POST /simulations": {
        "body_override": json.dumps(
            {
                "tool_id": "installment_vs_cash",
                "rule_version": "1.0",
                "inputs": {"cash_price": "1000.00"},
                "result": {"recommendation": "cash"},
            },
            indent=2,
        ),
        "test_lines": [
            "pm.test('Save simulation returns 201', function () {",
            "  pm.response.to.have.status(201);",
            "});",
            "var json = pm.response.json();",
            "// Response nests under data.simulation",
            "if (json.data && json.data.simulation) {",
            "  pm.collectionVariables.set('simulationId', json.data.simulation.id);",
            "}",
        ],
    },
    "POST /simulations/installment-vs-cash": {
        "body_override": json.dumps(
            {
                "cash_price": "900.00",
                "installment_count": 3,
                "installment_total": "990.00",
                "first_payment_delay_days": 30,
                "opportunity_rate_type": "manual",
                "opportunity_rate_annual": "12.00",
                "inflation_rate_annual": "4.50",
                "fees_enabled": False,
                "fees_upfront": "0.00",
            },
            indent=2,
        ),
        "test_lines": [
            "pm.test('Save installment-vs-cash returns 201', function () {",
            "  pm.response.to.have.status(201);",
            "});",
            "var json = pm.response.json();",
            "// Capture simulationId for bridge endpoints",
            "if (json.data && json.data.simulation) {",
            "  pm.collectionVariables.set('simulationId', json.data.simulation.id);",
            "}",
        ],
    },
    "POST /simulations/installment-vs-cash/calculate": {
        "body_override": json.dumps(
            {
                "cash_price": "900.00",
                "installment_count": 3,
                "installment_total": "990.00",
                "first_payment_delay_days": 30,
                "opportunity_rate_type": "manual",
                "opportunity_rate_annual": "12.00",
                "inflation_rate_annual": "4.50",
                "fees_enabled": False,
                "fees_upfront": "0.00",
            },
            indent=2,
        ),
    },
    "POST /simulations/installment-vs-cash/save": {
        "body_override": json.dumps(
            {
                "cash_price": "900.00",
                "installment_count": 3,
                "installment_total": "990.00",
                "first_payment_delay_days": 30,
                "opportunity_rate_type": "manual",
                "opportunity_rate_annual": "12.00",
                "inflation_rate_annual": "4.50",
                "fees_enabled": False,
                "fees_upfront": "0.00",
            },
            indent=2,
        ),
        "test_lines": [
            "pm.test('Save installment-vs-cash (legacy) returns 201', function () {",
            "  pm.response.to.have.status(201);",
            "});",
            "var json = pm.response.json();",
            "if (json.data && json.data.simulation) {",
            "  pm.collectionVariables.set('simulationId', json.data.simulation.id);",
            "}",
        ],
    },
    "POST /simulations/{simulation_id}/goal": {
        "body_override": json.dumps(
            {
                "title": "Meta da simulação {{runSeed}}",
                "selected_option": "cash",
                "target_date": "{{runIn365Days}}",
            },
            indent=2,
        ),
        "test_lines": [
            "// Bridge endpoint requires advanced_simulations entitlement — may 403",
            "pm.test('Goal bridge — expected 201 or 403', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([201, 403]);",
            "});",
        ],
    },
    "POST /simulations/{simulation_id}/planned-expense": {
        "body_override": json.dumps(
            {
                "title": "Despesa da simulação {{runSeed}}",
                "selected_option": "cash",
                "due_date": "{{runIn30Days}}",
            },
            indent=2,
        ),
        "test_lines": [
            "// Bridge endpoint requires advanced_simulations entitlement — may 403",
            "pm.test('Planned-expense bridge — expected 201 or 403', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([201, 403]);",
            "});",
        ],
    },
    # ── Entitlements ──────────────────────────────────────────────────
    "GET /entitlements/check": {
        "query_params": [{"key": "feature_key", "value": "advanced_simulations"}],
    },
    # ── Ops (may not be registered in CI) ─────────────────────────────
    "GET /ops/metrics": {
        "test_lines": [
            "// Ops endpoints may not be registered in all environments",
            "pm.test('Metrics — expected 200 or 404', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 404]);",
            "});",
        ],
    },
    "GET /ops/observability": {
        "test_lines": [
            "// Ops endpoints may not be registered in all environments",
            "pm.test('Observability — expected 200 or 404', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 404]);",
            "});",
        ],
    },
    # Avatar upload requires S3 credentials and a real file — CI has neither.
    # Accept 200 (success), 400 (no file / validation), or 500 (S3 not configured).
    "POST /user/me/avatar": {
        "test_lines": [
            "pm.test('Upload avatar do usuário — expected 200, 400 or 500', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 400, 500]);",
            "});",
        ],
    },
    # DELETE returns 404 when no avatar is set (common in CI after a failed POST).
    "DELETE /user/me/avatar": {
        "test_lines": [
            "pm.test('Remover avatar do usuário — expected 200 or 404', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 404]);",
            "});",
        ],
    },
    # Subscribe may return 400 in CI because the auto-generated body doesn't
    # contain a valid ExponentPushToken — our schema validation rejects it.
    "POST /notifications/subscribe": {
        "test_lines": [
            "pm.test('Registrar token de push — expected 200 or 400', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 400]);",
            "});",
        ],
    },
    # Unsubscribe returns 404 when subscribe failed in CI (no subscription exists).
    "POST /notifications/unsubscribe": {
        "test_lines": [
            "pm.test('Remover token de push — expected 200 or 404', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 404]);",
            "});",
        ],
    },
    # ── LGPD consents (#1259) ─────────────────────────────────────────
    # POST creates (201); the smoke run replays the same body so the
    # second pass exercises the idempotent path and may return 201 again
    # (record_consent returns the original row).
    "POST /me/consents": {
        "body_override": json.dumps(
            {
                "kind": "terms",
                "version": "1.0",
                "action": "granted",
                "source": "api",
            },
            indent=2,
        ),
        "test_lines": [
            "pm.test('Registrar consentimento — expected 201', function () {",
            "  pm.response.to.have.status(201);",
            "});",
        ],
    },
    "GET /me/consents": {
        "test_lines": [
            "pm.test('Listar consentimentos — expected 200', function () {",
            "  pm.response.to.have.status(200);",
            "});",
        ],
    },
    "DELETE /me/consents/{kind}": {
        "test_lines": [
            "pm.test('Revogar consentimento — expected 204', function () {",
            "  pm.response.to.have.status(204);",
            "});",
        ],
    },
    # ── LGPD export (#1256) ───────────────────────────────────────────
    "GET /user/me/export": {
        "test_lines": [
            "pm.test('LGPD export — expected 200', function () {",
            "  pm.response.to.have.status(200);",
            "});",
            "pm.test('LGPD export — has metadata block', function () {",
            "  const body = pm.response.json();",
            "  const data = body.data || body;",
            "  pm.expect(data).to.have.property('metadata');",
            "  pm.expect(data.metadata).to.have.property('scope', 'lgpd_full_export');",
            "  pm.expect(data.metadata).to.have.property('registry_version');",
            "});",
            "pm.test('LGPD export — has retentions section', function () {",
            "  const body = pm.response.json();",
            "  const data = body.data || body;",
            "  pm.expect(data).to.have.property('retentions');",
            "  pm.expect(data.retentions).to.be.an('array');",
            "});",
        ],
    },
    # ── AI Advisory ───────────────────────────────────────────────────
    "GET /ai/insights/spending": {
        "test_lines": [
            "pm.test('AI spending insights — expected 200 or 403 or 429', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 403, 429]);",
            "});",
        ],
    },
    "POST /ai/insights/spending-patterns": {
        "test_lines": [
            "// Premium gateway proxy to auraxis-api-v2. 503 when v2 unconfigured/down.",
            "pm.test('AI spending patterns — expected 200, 403, 429 or 503', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 403, 429, 503]);",
            "});",
        ],
    },
    "GET /ai/insights/weekly-summary": {
        "test_lines": [
            "pm.test('AI weekly summary — expected 200 or 403 or 429', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 403, 429]);",
            "});",
        ],
    },
    "POST /ai/insights/generate": {
        "body_override": json.dumps(
            {"period_type": "daily", "anchor_date": "{{runToday}}"},
            indent=2,
        ),
        "test_lines": [
            "pm.test('AI period insight — expected 200 or 403 or 429', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 403, 429]);",
            "});",
        ],
    },
    "POST /ai/goals/{goal_id}/projection": {
        "test_lines": [
            "pm.test('AI goal projection — expected 200 or 400 or 403 or 404', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 400, 403, 404]);",
            "});",
        ],
    },
    "GET /ai/insights/history": {
        "test_lines": [
            "pm.test('AI insights history — expected 200 or 401', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 401]);",
            "});",
        ],
    },
    "GET /ai/insights/{insight_id}": {
        "test_lines": [
            "pm.test('Buscar AI Insight por id — expected 200, 400 or 404', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 400, 404]);",
            "});",
        ],
    },
    "GET /ai/insights/runs/{run_id}": {
        "test_lines": [
            "pm.test('Consultar status de run de AI Insight — expected 200, 400 or 404', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 400, 404]);",
            "});",
        ],
    },
    "POST /ai/insights/monthly-report": {
        "body_override": json.dumps(
            {"anchor_date": "2026-05-21", "enqueue": True},
            indent=2,
        ),
        "test_lines": [
            "pm.test('Solicitar relatório mensal com IA — expected 200, 202, 403 or 429', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([200, 202, 403, 429]);",
            "});",
        ],
    },
    "POST /ai/insights/{insight_id}/feedback": {
        # The smoke run targets a placeholder insight_id with an auto-generated
        # body, so it never owns a real insight — expect 400 (bad path/body) or
        # 404 (insight not found/owned), with 201 on the happy path.
        "test_lines": [
            "pm.test('Enviar feedback de um insight de IA — expected 201, 400 or 404', function () {",
            "  pm.expect(pm.response.code).to.be.oneOf([201, 400, 404]);",
            "});",
        ],
    },
}

# ---------------------------------------------------------------------------
# Helper: Postman request/item builders
# ---------------------------------------------------------------------------


def _js(lines: list[str]) -> dict[str, Any]:
    return {"exec": lines, "type": "text/javascript"}


def _resolve_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    """Resolve a $ref pointer like '#/components/schemas/Foo'."""
    parts = ref.lstrip("#/").split("/")
    node: Any = spec
    for part in parts:
        node = node.get(part, {})
    return node if isinstance(node, dict) else {}


def _example_from_schema(
    spec: dict[str, Any], schema: dict[str, Any], depth: int = 0
) -> Any:
    """Generate a sample value from an OpenAPI schema (best-effort)."""
    if depth > 4:
        return {}
    if "$ref" in schema:
        schema = _resolve_ref(spec, schema["$ref"])
    if "example" in schema:
        return schema["example"]
    schema_type = schema.get("type", "object")
    if schema_type == "object":
        props = schema.get("properties", {})
        return {k: _example_from_schema(spec, v, depth + 1) for k, v in props.items()}
    if schema_type == "array":
        items = schema.get("items", {})
        return [_example_from_schema(spec, items, depth + 1)]
    if schema_type == "string":
        fmt = schema.get("format", "")
        if fmt == "date":
            return "2026-01-01"
        if fmt == "date-time":
            return "2026-01-01T00:00:00Z"
        if fmt == "email":
            return "user@example.com"
        if fmt == "uuid":
            return "00000000-0000-4000-8000-000000000001"
        return schema.get("enum", ["string"])[0] if "enum" in schema else "string"
    if schema_type == "integer":
        return 1
    if schema_type == "number":
        return 1.0
    if schema_type == "boolean":
        return True
    return None


def _extract_body(spec: dict[str, Any], operation: dict[str, Any]) -> str | None:
    """Extract a JSON body example from requestBody or body parameter."""
    # OpenAPI 3.x requestBody
    rb = operation.get("requestBody", {})
    content = rb.get("content", {}).get("application/json", {})
    if "example" in content:
        return json.dumps(content["example"], indent=2, ensure_ascii=False)
    if "schema" in content:
        sample = _example_from_schema(spec, content["schema"])
        if sample:
            return json.dumps(sample, indent=2, ensure_ascii=False)
    # Swagger 2.x body parameter
    for param in operation.get("parameters", []):
        if param.get("in") == "body" and "schema" in param:
            sample = _example_from_schema(spec, param["schema"])
            if sample:
                return json.dumps(sample, indent=2, ensure_ascii=False)
    return None


def _postman_url(path: str) -> dict[str, Any]:
    """Build a Postman URL object from an OpenAPI path."""
    # Replace {param} with :param for Postman path variables
    postman_path = re.sub(r"\{(\w+)\}", r":\1", path)
    segments = [s for s in postman_path.split("/") if s]
    return {
        "raw": "{{baseUrl}}" + postman_path,
        "host": ["{{baseUrl}}"],
        "path": segments,
    }


def _postman_path_variables(path: str) -> list[dict[str, str]]:
    """Extract path variable placeholders."""
    variables = []
    for match in re.finditer(r"\{(\w+)\}", path):
        name = match.group(1)
        # Map to collection variables where possible
        var_map = {
            "transaction_id": "{{transactionId}}",
            "goal_id": "{{goalId}}",
            "investment_id": "{{investmentId}}",
            "operation_id": "{{operationId}}",
            "simulation_id": "{{simulationId}}",
            "budget_id": "{{budgetId}}",
            "entitlement_id": "{{entitlementId}}",
            # LGPD consents (#1259): static valid enum value for smoke tests.
            "kind": "terms",
        }
        variables.append({"key": name, "value": var_map.get(name, f"<{name}>")})
    return variables


def _default_test_lines(method: str, path: str, operation: dict[str, Any]) -> list[str]:
    """Generate basic status code assertion."""
    responses = operation.get("responses", {})
    expected_codes = sorted(responses.keys())
    # Pick the success code
    success = "200"
    for code in expected_codes:
        if code.startswith("2"):
            success = code
            break
    summary = operation.get("summary", f"{method.upper()} {path}")
    safe_summary = summary.replace("'", "\\'")
    return [
        f"pm.test('{safe_summary} — status {success}', function () {{",
        f"  pm.response.to.have.status({success});",
        "});",
    ]


def _request_name(method: str, path: str, operation: dict[str, Any]) -> str:
    """Human-readable request name."""
    summary = operation.get("summary", "")
    if summary:
        return f"{method.upper()} — {summary}"
    # Fallback: method + path
    return f"{method.upper()} {path}"


# ---------------------------------------------------------------------------
# Suite profile pre-request (collection-level)
# ---------------------------------------------------------------------------


def _build_smoke_list(items: list[dict[str, Any]]) -> list[str]:
    """Collect request names that belong to the smoke profile."""
    names = []
    for folder in items:
        for item in folder.get("item", []):
            if item.get("_smoke"):
                names.append(item["name"])
    return names


def _build_privileged_list(items: list[dict[str, Any]]) -> list[str]:
    """Collect request names that belong to the privileged profile."""
    names = []
    for folder in items:
        for item in folder.get("item", []):
            if item.get("_privileged"):
                names.append(item["name"])
    return names


def _suite_profile_prerequest(
    smoke_names: list[str], privileged_names: list[str]
) -> list[str]:
    smoke_json = json.dumps(smoke_names, ensure_ascii=True)
    privileged_json = json.dumps(privileged_names, ensure_ascii=True)
    return [
        f"var smokeRequests = {smoke_json};",
        f"var privilegedOnlyRequests = {privileged_json};",
        "var activeProfile = String(pm.environment.get('suiteProfile') || pm.collectionVariables.get('suiteProfile') || 'full').toLowerCase();",
        "if (!['smoke', 'full', 'privileged'].includes(activeProfile)) {",
        "  throw new Error('Unsupported suiteProfile: ' + activeProfile + '. Use smoke, full or privileged.');",
        "}",
        "pm.collectionVariables.set('suiteProfile', activeProfile);",
        "if (activeProfile === 'smoke' && !smokeRequests.includes(pm.info.requestName)) {",
        "  pm.execution.skipRequest();",
        "}",
        "if (activeProfile === 'full' && privilegedOnlyRequests.includes(pm.info.requestName)) {",
        "  pm.execution.skipRequest();",
        "}",
    ]


def _bootstrap_prerequest() -> list[str]:
    return [
        "// Bootstrap once — keep seed/email stable across the entire run",
        "if (!pm.collectionVariables.get('runSeed')) {",
        "  var now = new Date();",
        "  var seed = String(now.getTime());",
        "  function isoDate(offsetDays) {",
        "    var d = new Date(now);",
        "    d.setUTCDate(d.getUTCDate() + offsetDays);",
        "    return d.toISOString().slice(0, 10);",
        "  }",
        "  function isoMonth(offsetMonths) {",
        "    var d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + offsetMonths, 1));",
        "    return d.toISOString().slice(0, 7);",
        "  }",
        "  pm.collectionVariables.set('runSeed', seed);",
        "  pm.collectionVariables.set('runEmail', 'auraxis+' + seed + '@example.com');",
        "  pm.collectionVariables.set('runName', 'auraxis_' + seed);",
        "  pm.collectionVariables.set('runToday', isoDate(0));",
        "  pm.collectionVariables.set('runYesterday', isoDate(-1));",
        "  pm.collectionVariables.set('runTomorrow', isoDate(1));",
        "  pm.collectionVariables.set('runIn30Days', isoDate(30));",
        "  pm.collectionVariables.set('runIn45Days', isoDate(45));",
        "  pm.collectionVariables.set('runIn60Days', isoDate(60));",
        "  pm.collectionVariables.set('runIn180Days', isoDate(180));",
        "  pm.collectionVariables.set('runIn365Days', isoDate(365));",
        "  pm.collectionVariables.set('runMonthRef', isoMonth(0));",
        "}",
    ]


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------


def build_collection(spec: dict[str, Any]) -> dict[str, Any]:
    """Convert an OpenAPI spec dict to a Postman Collection v2.1 dict."""
    folders: dict[str, list[dict[str, Any]]] = {}

    for path, methods in sorted(spec.get("paths", {}).items()):
        for method in sorted(methods.keys()):
            if method == "options":
                continue  # skip CORS preflight
            operation = methods[method]
            if not isinstance(operation, dict):
                continue

            op_key = f"{method.upper()} {path}"

            # Per-operation override takes highest priority
            folder_name = OPERATION_FOLDER_OVERRIDE.get(op_key, "")
            if not folder_name:
                tags = operation.get("tags", [])
                tag = tags[0] if tags else "Untagged"
                folder_name = TAG_FOLDER_MAP.get(tag, "")
                if not folder_name or tag == "Untagged":
                    # Fallback: match path prefix
                    for prefix, fname in PATH_FOLDER_FALLBACK.items():
                        if path.startswith(prefix):
                            folder_name = fname
                            break
                    else:
                        folder_name = DEFAULT_FOLDER

            # --- Headers ---
            headers: list[dict[str, str]] = [
                {"key": "X-API-Contract", "value": "v2"},
            ]
            needs_auth = path not in PUBLIC_PATHS
            if needs_auth:
                headers.append(
                    {"key": "Authorization", "value": "Bearer {{authToken}}"}
                )

            # --- Body ---
            enrichment = ENRICHMENT.get(op_key, {})
            body_str: str | None = None
            if enrichment.get("no_body"):
                body_str = None
            else:
                body_str = enrichment.get("body_override") or _extract_body(
                    spec, operation
                )
            # POST/PUT/PATCH always need Content-Type — Flask returns 415
            # if missing, even when body is empty (controller calls get_json()).
            if method.upper() in ("POST", "PUT", "PATCH") or body_str:
                headers.insert(0, {"key": "Content-Type", "value": "application/json"})

            # --- Request object ---
            url_obj = _postman_url(path)
            # Enrichment query params (e.g. ?month={{runMonthRef}})
            query_params = enrichment.get("query_params")
            if query_params:
                url_obj["query"] = query_params
                qs = "&".join(f"{p['key']}={p['value']}" for p in query_params)
                url_obj["raw"] += "?" + qs

            request: dict[str, Any] = {
                "method": method.upper(),
                "header": headers,
                "url": url_obj,
            }
            path_vars = _postman_path_variables(path)
            if path_vars:
                request["url"]["variable"] = path_vars
            if body_str:
                request["body"] = {"mode": "raw", "raw": body_str}

            # --- Events ---
            events: list[dict[str, Any]] = []
            test_lines = enrichment.get("test_lines") or _default_test_lines(
                method, path, operation
            )
            events.append({"listen": "test", "script": _js(test_lines)})

            prerequest_lines = enrichment.get("prerequest_lines")
            if prerequest_lines:
                events.append({"listen": "prerequest", "script": _js(prerequest_lines)})

            # --- Item ---
            name = _request_name(method, path, operation)
            item: dict[str, Any] = {
                "name": name,
                "request": request,
                "event": events,
            }

            # Internal markers (stripped before output)
            item["_op_key"] = op_key
            if op_key in SMOKE_OPERATIONS:
                item["_smoke"] = True
            if op_key in PRIVILEGED_OPERATIONS:
                item["_privileged"] = True

            folders.setdefault(folder_name, []).append(item)

    # --- Sort items within each folder using OPERATION_ORDER ---
    for folder_name, folder_items in folders.items():
        priority = OPERATION_ORDER.get(folder_name, [])
        priority_index = {op_key: i for i, op_key in enumerate(priority)}

        def _sort_key(
            item: dict[str, Any],
            _pi: dict[str, int] = priority_index,
            _plen: int = len(priority),
        ) -> tuple[int, str]:
            op_key = item.get("_op_key", "")
            if op_key in _pi:
                return (_pi[op_key], op_key)
            return (_plen, item.get("name", ""))

        folder_items.sort(key=_sort_key)

    # --- Assemble folder items in order ---
    ordered_items: list[dict[str, Any]] = []
    for folder_name in FOLDER_ORDER:
        if folder_name in folders:
            ordered_items.append({"name": folder_name, "item": folders[folder_name]})
    # Any remaining folders not in FOLDER_ORDER
    for folder_name in sorted(folders.keys()):
        if folder_name not in {f["name"] for f in ordered_items}:
            ordered_items.append({"name": folder_name, "item": folders[folder_name]})

    # --- Build profile lists ---
    smoke_names = _build_smoke_list(ordered_items)
    privileged_names = _build_privileged_list(ordered_items)

    # --- Strip internal markers ---
    for folder in ordered_items:
        for item in folder.get("item", []):
            item.pop("_smoke", None)
            item.pop("_privileged", None)
            item.pop("_op_key", None)

    # --- Collection-level events ---
    collection_events = [
        {
            "listen": "prerequest",
            "script": _js(
                _bootstrap_prerequest()
                + [""]
                + _suite_profile_prerequest(smoke_names, privileged_names)
            ),
        },
    ]

    # --- Collection variables ---
    collection_variables = [
        {"key": "baseUrl", "value": "http://localhost:5000"},
        {"key": "testPassword", "value": "Test@123456"},
        {"key": "suiteProfile", "value": "full"},
        {"key": "authToken", "value": ""},
        {"key": "refreshToken", "value": ""},
        {"key": "userId", "value": ""},
        {"key": "transactionId", "value": ""},
        {"key": "goalId", "value": ""},
        {"key": "investmentId", "value": ""},
        {"key": "operationId", "value": ""},
        {"key": "simulationId", "value": ""},
        {"key": "budgetId", "value": ""},
        {"key": "entitlementId", "value": ""},
        {"key": "runSeed", "value": ""},
        {"key": "runEmail", "value": ""},
        {"key": "runName", "value": ""},
        {"key": "runToday", "value": ""},
        {"key": "runYesterday", "value": ""},
        {"key": "runTomorrow", "value": ""},
        {"key": "runIn30Days", "value": ""},
        {"key": "runIn45Days", "value": ""},
        {"key": "runIn60Days", "value": ""},
        {"key": "runIn180Days", "value": ""},
        {"key": "runIn365Days", "value": ""},
        {"key": "runMonthRef", "value": ""},
    ]

    return {
        "info": {
            "name": "Auraxis API",
            "description": f"Auto-generated from openapi.json ({len(spec.get('paths', {}))} paths). Do not edit manually — regenerate with: npm run postman:build",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": ordered_items,
        "event": collection_events,
        "variable": collection_variables,
    }


def main() -> None:
    if not OPENAPI_PATH.exists():
        raise SystemExit(
            f"ERROR: {OPENAPI_PATH} not found. Run: flask openapi-export --output openapi.json"
        )

    spec = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    collection = build_collection(spec)

    COLLECTION_PATH.parent.mkdir(parents=True, exist_ok=True)
    COLLECTION_PATH.write_text(
        json.dumps(collection, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    total_requests = sum(len(folder.get("item", [])) for folder in collection["item"])
    print(
        f"Postman collection written to {COLLECTION_PATH.relative_to(ROOT)} "
        f"({total_requests} requests in {len(collection['item'])} folders)"
    )


if __name__ == "__main__":
    main()
