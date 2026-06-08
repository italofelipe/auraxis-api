# mypy: disable-error-code="name-defined,no-redef"

import uuid
from datetime import UTC, datetime, timedelta

from flask import current_app
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.hybrid import hybrid_property

from app.extensions.database import db
from app.utils.datetime_utils import utc_now_naive


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    name = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(128), nullable=False, unique=True)
    password = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now_naive)
    updated_at = db.Column(db.DateTime, default=utc_now_naive)
    current_jti = db.Column(db.String(128), nullable=True)
    refresh_token_jti = db.Column(db.String(128), nullable=True)
    password_reset_token_hash = db.Column(db.String(128), nullable=True)
    password_reset_token_expires_at = db.Column(db.DateTime, nullable=True)
    password_reset_requested_at = db.Column(db.DateTime, nullable=True)
    email_verification_token_hash = db.Column(db.String(128), nullable=True)
    email_verification_token_expires_at = db.Column(db.DateTime, nullable=True)
    email_verification_requested_at = db.Column(db.DateTime, nullable=True)
    email_verified_at = db.Column(db.DateTime, nullable=True)

    # Personal data collected after the initial signup flow.
    gender = db.Column(db.String(20), nullable=True)
    birth_date = db.Column(db.Date, nullable=True)
    monthly_income_net = db.Column(db.Numeric(10, 2), nullable=True)
    net_worth = db.Column(db.Numeric(10, 2), nullable=True)
    monthly_expenses = db.Column(db.Numeric(10, 2), nullable=True)
    initial_investment = db.Column(db.Numeric(10, 2), nullable=True)
    monthly_investment = db.Column(db.Numeric(10, 2), nullable=True)
    investment_goal_date = db.Column(db.Date, nullable=True)

    state_uf = db.Column(db.String(2), nullable=True)
    occupation = db.Column(db.String(128), nullable=True)

    # Allowed values: conservador/explorador/entusiasta
    investor_profile = db.Column(db.String(32), nullable=True)

    financial_objectives = db.Column(db.Text, nullable=True)

    # Suggested profile derived from questionnaire (indicative only)
    investor_profile_suggested = db.Column(db.String(32), nullable=True)
    profile_quiz_score = db.Column(db.Integer, nullable=True)
    taxonomy_version = db.Column(db.String(16), nullable=True)

    # J12 — subscription entitlement version bump.
    # Clients compare their cached value with this field to detect that
    # entitlements changed and must be revalidated (avoids polling).
    # Incremented atomically on subscription_status_changed events.
    entitlements_version = db.Column(db.Integer, nullable=False, default=0)

    # User avatar — URL of the uploaded image stored in S3/CDN.
    avatar_url = db.Column(db.String(500), nullable=True)

    # Onboarding — server-side completion marker (#1471).
    # Persisted so clearing browser storage on any device does NOT re-trigger
    # the onboarding wizard. Null means the user has not finished onboarding.
    onboarding_completed_at = db.Column(db.DateTime, nullable=True)

    # LGPD — soft-delete / account erasure.
    # When set, this account has been anonymised and must be treated as deleted.
    deleted_at = db.Column(db.DateTime, nullable=True)

    tickers = db.relationship("UserTicker", back_populates="user")
    goals = db.relationship(
        "Goal",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<User {self.name}>"

    def validate_profile_data(self) -> list[str]:
        from app.services.user_validations import validate_user_profile_data

        return validate_user_profile_data(self)

    @hybrid_property
    def monthly_income(self):
        return self.monthly_income_net

    @monthly_income.setter
    def monthly_income(self, value):
        self.monthly_income_net = value

    @hybrid_property
    def email_verified(self) -> bool:
        """True se o email do usuário foi confirmado."""
        return self.email_verified_at is not None

    @hybrid_property
    def email_verification_deadline_at(self) -> datetime | None:
        """Timestamp limite para confirmar email; None se já verificado.

        Após esse prazo, o usuário entra em modo soft-block (mutations bloqueadas
        retornam 403 EMAIL_VERIFICATION_REQUIRED). Reads continuam liberados.
        """
        if self.email_verified_at is not None:
            return None
        if self.created_at is None:
            return None
        grace_days = int(
            current_app.config.get("EMAIL_VERIFICATION_GRACE_PERIOD_DAYS", 14)
        )
        deadline: datetime = self.created_at + timedelta(days=grace_days)
        return deadline

    @hybrid_property
    def email_verification_required_now(self) -> bool:
        """True se o grace period expirou e o email ainda não foi confirmado.

        Usado pelo decorator @require_email_verified para retornar 403 em
        endpoints de mutation.
        """
        if self.email_verified_at is not None:
            return False
        deadline = self.email_verification_deadline_at
        if deadline is None:
            return False
        return datetime.now(UTC).replace(tzinfo=None) > deadline

    @hybrid_property
    def days_until_email_required(self) -> int | None:
        """Dias restantes até o grace period expirar; None se já verificado.

        Pode ser <= 0 (já expirou — frontend usa para mostrar gate, não countdown).
        """
        if self.email_verified_at is not None:
            return None
        deadline = self.email_verification_deadline_at
        if deadline is None:
            return None
        remaining = deadline - datetime.now(UTC).replace(tzinfo=None)
        return remaining.days
