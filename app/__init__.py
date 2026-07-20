import os
from collections.abc import Mapping
from typing import Any

from apispec import APISpec
from apispec.ext.marshmallow import MarshmallowPlugin
from flask import Flask, jsonify
from flask.typing import ResponseReturnValue
from flask_apispec import FlaskApiSpec
from flask_jwt_extended import JWTManager
from flask_marshmallow import Marshmallow
from flask_migrate import Migrate
from sqlalchemy.pool import NullPool

from app.cli.ai_insights_cli import register_ai_insights_commands
from app.cli.features import features as features_cli_group
from app.cli.openapi_export import openapi_export_command
from app.cli.premium_overrides_cli import register_premium_override_commands
from app.cli.recurrence_cli import register_recurrence_commands
from app.cli.transactions_cli import register_transactions_commands
from app.cli.worker_cli import worker_cli_group
from app.controllers.account import account_bp
from app.controllers.admin.ai_insights import admin_ai_insights_bp
from app.controllers.admin.audit_trail import admin_audit_trail_bp
from app.controllers.admin.feature_flags import admin_feature_flags_bp
from app.controllers.advisory import advisory_bp
from app.controllers.ai import ai_bp
from app.controllers.alert_controller import alert_bp, register_alert_dependencies
from app.controllers.auth_controller import auth_bp, register_auth_dependencies
from app.controllers.bank_statement import bank_statement_bp
from app.controllers.budget import budget_bp
from app.controllers.consents import consents_bp
from app.controllers.consents import routes as _consent_routes  # noqa: F401
from app.controllers.credit_card import credit_card_bp
from app.controllers.dashboard import dashboard_bp
from app.controllers.entitlement import (
    entitlement_bp,
    register_entitlement_dependencies,
)
from app.controllers.fiscal import fiscal_bp
from app.controllers.goal_controller import goal_bp, register_goal_dependencies
from app.controllers.graphql_controller import graphql_bp, register_graphql_dependencies
from app.controllers.health_controller import health_bp
from app.controllers.notifications import routes as _notification_routes  # noqa: F401
from app.controllers.notifications.blueprint import notifications_bp
from app.controllers.observability_controller import observability_bp
from app.controllers.shared_entries import (
    register_shared_entries_dependencies,
    shared_entries_bp,
)
from app.controllers.simulation import (
    register_simulation_dependencies,
    simulation_bp,
)
from app.controllers.subscription_controller import subscription_bp
from app.controllers.tag import tag_bp
from app.controllers.transaction_controller import (
    register_transaction_dependencies,
    transaction_bp,
)
from app.controllers.user_controller import register_user_dependencies, user_bp
from app.controllers.wallet_controller import register_wallet_dependencies, wallet_bp
from app.docs.api_documentation import API_INFO, TAGS
from app.docs.schema_name_resolver import resolve_openapi_schema_name
from app.extensions.audit_retention_cli import register_audit_retention_commands
from app.extensions.audit_trail import register_audit_trail
from app.extensions.billing_webhooks_cli import register_billing_webhooks_commands
from app.extensions.database import db
from app.extensions.email_dlq_cli import register_email_dlq_commands
from app.extensions.error_handlers import register_error_handlers
from app.extensions.http_observability import register_http_observability
from app.extensions.integration_metrics_cli import register_integration_metrics_commands
from app.extensions.otel import init_otel
from app.extensions.prometheus_metrics import register_prometheus_middleware
from app.extensions.reminders_cli import register_reminders_commands
from app.extensions.sentry import init_sentry
from app.extensions.slow_query_log import install_slow_query_log
from app.extensions.trial_expiry_cli import register_trial_expiry_cli
from app.http.request_context import register_request_context_adapter
from app.middleware.correlation_id import register_correlation_id
from app.middleware.cors import register_cors
from app.middleware.docs_access import register_docs_access_guard
from app.middleware.security_headers import register_security_headers
from app.models.account import Account  # noqa: F401
from app.models.ai_insight import AIInsight  # noqa: F401
from app.models.ai_insight_run import AIInsightRun  # noqa: F401
from app.models.audit_event import AuditEvent  # noqa: F401
from app.models.budget import Budget  # noqa: F401
from app.models.consent import Consent  # noqa: F401
from app.models.credit_card import CreditCard  # noqa: F401
from app.models.entitlement import Entitlement  # noqa: F401
from app.models.fiscal import (  # noqa: F401
    FiscalAdjustment,
    FiscalDocument,
    FiscalImport,
    ReceivableEntry,
)
from app.models.goal import Goal  # noqa: F401
from app.models.goal_contribution import GoalContribution  # noqa: F401
from app.models.investment_operation import InvestmentOperation  # noqa: F401
from app.models.llm_audit_log import LLMAuditLog  # noqa: F401
from app.models.premium_override import PremiumOverride  # noqa: F401
from app.models.refresh_token import RefreshToken  # noqa: F401
from app.models.shared_entry import Invitation, SharedEntry  # noqa: F401
from app.models.sharing_audit import SharingAuditEvent  # noqa: F401
from app.models.simulation import Simulation  # noqa: F401
from app.models.simulation_quota_usage import (  # noqa: F401
    SimulationQuotaUsage,
)
from app.models.subscription import Subscription  # noqa: F401
from app.models.tag import Tag  # noqa: F401
from app.models.webhook_event import WebhookEvent  # noqa: F401

jwt = JWTManager()
ma = Marshmallow()
DOCS_CLASS_REGISTRATION_FALLBACK_ENDPOINTS = {
    "goal.goal_collection",
    "simulation.simulation_collection",
}


def _register_http_runtime(app: Flask) -> None:
    register_request_context_adapter(app)
    register_correlation_id(app)
    register_http_observability(app)
    register_prometheus_middleware(app)
    register_cors(app)
    register_security_headers(app)
    register_docs_access_guard(app)


def _coerce_openapi_numeric_bound(value: object) -> object:
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return value
        return int(number) if number.is_integer() else number
    return value


def _normalize_openapi_numbers(node: object) -> object:
    numeric_bound_keys = {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
    }
    if isinstance(node, dict):
        normalized: dict[str, object] = {}
        for key, value in node.items():
            normalized[key] = (
                _coerce_openapi_numeric_bound(value)
                if key in numeric_bound_keys
                else _normalize_openapi_numbers(value)
            )
        return normalized
    if isinstance(node, list):
        return [_normalize_openapi_numbers(item) for item in node]
    return node


def _register_normalized_swagger_json_route(app: Flask, docs: FlaskApiSpec) -> None:
    def normalized_swagger_json() -> ResponseReturnValue:
        return jsonify(_normalize_openapi_numbers(docs.spec.to_dict()))

    for endpoint_name in ("flask-apispec.swagger-json", "flask-apispec.swagger_json"):
        if endpoint_name in app.view_functions:
            app.view_functions[endpoint_name] = normalized_swagger_json


def _register_documented_endpoints(app: Flask, docs: FlaskApiSpec) -> None:
    documented_blueprints = {
        "auth",
        "user",
        "transaction",
        "dashboard",
        "goal",
        "wallet",
        "health",
        "entitlement",
        "simulation",
        "observability",
        "budget",
        "notifications",
        "consents",
        "ai",
    }
    for endpoint, view_func in sorted(app.view_functions.items()):
        if "." not in endpoint:
            continue
        blueprint, endpoint_name = endpoint.split(".", 1)
        if blueprint not in documented_blueprints:
            continue
        docs_target = getattr(view_func, "view_class", view_func)
        if endpoint in DOCS_CLASS_REGISTRATION_FALLBACK_ENDPOINTS:
            docs_target = view_func
        docs.register(docs_target, blueprint=blueprint, endpoint=endpoint_name)


def create_app(*, enable_http_runtime: bool = True) -> Flask:
    # Sentry must be initialised before anything else so it can capture
    # startup errors. Safe no-op when SENTRY_DSN is not set.
    init_sentry()

    app = Flask(__name__, instance_relative_config=True)

    from config import Config, validate_security_configuration

    app.config.from_object(Config)
    runtime_database_url = os.getenv("DATABASE_URL")
    if runtime_database_url:
        app.config["SQLALCHEMY_DATABASE_URI"] = runtime_database_url

    # Carrega variáveis de ambiente com prefixo FLASK_ do .env
    app.config.from_prefixed_env()
    app.config["MAX_CONTENT_LENGTH"] = int(
        os.getenv("MAX_REQUEST_BYTES", str(10 * 1024 * 1024))
    )
    # Prevent SQLite connection pooling in tests to avoid leaked connections
    # surfacing as ResourceWarning under newer Python versions.
    if os.getenv("FLASK_TESTING", "false").strip().lower() == "true":
        db_uri = str(app.config.get("SQLALCHEMY_DATABASE_URI", ""))
        if db_uri.startswith("sqlite"):
            app.config.setdefault("SQLALCHEMY_ENGINE_OPTIONS", {})
            opts = app.config["SQLALCHEMY_ENGINE_OPTIONS"]
            # NullPool is incompatible with pool-sizing options (pool_size,
            # max_overflow, pool_timeout) — strip them before applying NullPool
            # so that configs tuned for PostgreSQL don't break SQLite in tests.
            for _k in ("pool_size", "max_overflow", "pool_timeout"):
                opts.pop(_k, None)
            opts["poolclass"] = NullPool
    validate_security_configuration()

    # Inicializa extensões
    db.init_app(app)
    ma.init_app(app)
    Migrate(app, db)
    jwt.init_app(app)

    # PERF-3 — slow query log listeners on the default SQLAlchemy engine.
    install_slow_query_log(app)

    # OTel tracing — no-op when OTEL_EXPORTER_OTLP_ENDPOINT is unset.
    # Must be called after db.init_app() so SQLAlchemy instrumentation can
    # access the engine.
    with app.app_context():
        init_otel(app)

    # Schema bootstrap deve ser explicito para evitar drift em runtime seguro.
    auto_create_db = os.getenv("AUTO_CREATE_DB", "false").lower() == "true"
    if auto_create_db:
        with app.app_context():
            db.create_all()

    # Configuração do Swagger (OpenAPI 3.0) com documentação melhorada
    app.config.update(
        {
            "APISPEC_SPEC": APISpec(
                title=str(API_INFO["title"]),
                version=str(API_INFO["version"]),
                openapi_version="3.0.2",
                plugins=[
                    MarshmallowPlugin(schema_name_resolver=resolve_openapi_schema_name)
                ],
                info={
                    "description": API_INFO["description"],
                    "contact": API_INFO["contact"],
                    "license": API_INFO["license"],
                },
                components={
                    "securitySchemes": {
                        "BearerAuth": {
                            "type": "http",
                            "scheme": "bearer",
                            "bearerFormat": "JWT",
                            "description": "Token JWT obtido através do login",
                        }
                    }
                },
                tags=TAGS,
            ),
            "APISPEC_SWAGGER_URL": "/docs/swagger/",  # JSON da spec
            "APISPEC_SWAGGER_UI_URL": "/docs/",  # Swagger UI
            "APISPEC_OPTIONS": {"security": [{"BearerAuth": []}]},
        }
    )

    docs = FlaskApiSpec(app)
    _register_normalized_swagger_json_route(app, docs)

    # Registra erros globais
    register_error_handlers(app)
    register_graphql_dependencies(app)
    register_auth_dependencies(app)
    register_user_dependencies(app)
    register_transaction_dependencies(app)
    register_goal_dependencies(app)
    register_alert_dependencies(app)
    if enable_http_runtime:
        _register_http_runtime(app)
    register_audit_trail(app)
    register_audit_retention_commands(app)
    register_trial_expiry_cli(app)
    register_integration_metrics_commands(app)
    register_billing_webhooks_commands(app)
    register_reminders_commands(app)
    register_ai_insights_commands(app)
    register_recurrence_commands(app)
    register_transactions_commands(app)
    register_premium_override_commands(app)
    register_email_dlq_commands(app)
    app.cli.add_command(features_cli_group, "features")
    app.cli.add_command(openapi_export_command)
    app.cli.add_command(worker_cli_group, "worker")
    register_wallet_dependencies(app)
    register_entitlement_dependencies(app)
    register_simulation_dependencies(app)
    register_shared_entries_dependencies(app)

    # Registra blueprints ANTES dos endpoints no Swagger
    app.register_blueprint(transaction_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(goal_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(wallet_bp)
    app.register_blueprint(graphql_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(observability_bp)
    app.register_blueprint(alert_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(bank_statement_bp)
    app.register_blueprint(credit_card_bp)
    app.register_blueprint(subscription_bp)
    app.register_blueprint(entitlement_bp)
    app.register_blueprint(simulation_bp)
    app.register_blueprint(shared_entries_bp)
    app.register_blueprint(fiscal_bp)
    app.register_blueprint(tag_bp)
    app.register_blueprint(budget_bp)
    app.register_blueprint(advisory_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(consents_bp)
    app.register_blueprint(admin_feature_flags_bp, url_prefix="/admin")
    app.register_blueprint(admin_ai_insights_bp, url_prefix="/admin")
    app.register_blueprint(admin_audit_trail_bp)

    # Registra os endpoints documentados no Swagger com base no mapa real de rotas.
    _register_documented_endpoints(app, docs)
    from app.extensions.jwt_callbacks import register_jwt_callbacks
    from app.middleware.auth_guard import register_auth_guard
    from app.middleware.idempotency_key import register_idempotency_guard
    from app.middleware.rate_limit import register_rate_limit_guard

    if enable_http_runtime:
        register_rate_limit_guard(app)
        register_auth_guard(app)
        register_idempotency_guard(app)
    register_jwt_callbacks(jwt)

    return app


__all__ = ["create_app"]
