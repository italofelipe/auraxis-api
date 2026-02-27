# mypy: disable-error-code="name-defined,no-redef"

import uuid
from datetime import datetime

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.hybrid import hybrid_property

from app.extensions.database import db


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    name = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(128), nullable=False, unique=True)
    password = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now)
    current_jti = db.Column(db.String(128), nullable=True)
    password_reset_token_hash = db.Column(db.String(128), nullable=True)
    password_reset_token_expires_at = db.Column(db.DateTime, nullable=True)
    password_reset_requested_at = db.Column(db.DateTime, nullable=True)

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

    investor_profile_suggested = db.Column(db.String(32), nullable=True)
    profile_quiz_score = db.Column(db.Integer, nullable=True)
    taxonomy_version = db.Column(db.String(16), nullable=True)

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
