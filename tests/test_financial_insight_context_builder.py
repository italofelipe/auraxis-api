"""Tests for the financial snapshot builder used by AI insights (#1269)."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from inspect import getsource
from typing import Any
from unittest.mock import patch

from app.extensions.database import db
from app.models.budget import Budget
from app.models.credit_card import CreditCard
from app.models.goal import Goal
from app.models.goal_contribution import GoalContribution
from app.models.transaction import (
    Transaction,
    TransactionCategory,
    TransactionStatus,
    TransactionType,
)
from app.models.user import User
from app.models.wallet import Wallet
from app.services import financial_insight_context_builder
from app.services.financial_insight_context_builder import (
    FinancialInsightContextBuilder,
)


def _make_user() -> uuid.UUID:
    user = User(
        name="Ana Cliente",
        email=f"ana-{uuid.uuid4().hex[:8]}@example.com",
        password="hashed",
    )
    db.session.add(user)
    db.session.commit()
    return user.id


def _make_transaction(
    user_id: uuid.UUID,
    *,
    title: str,
    amount: str,
    tx_type: TransactionType,
    status: TransactionStatus,
    due_date: date,
    category: TransactionCategory | None = None,
    description: str | None = None,
    observation: str | None = None,
    external_id: str | None = None,
    bank_name: str | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    paid_at: datetime | None = None,
    credit_card_id: uuid.UUID | None = None,
) -> Transaction:
    tx = Transaction(
        user_id=user_id,
        title=title,
        description=description if description is not None else title,
        observation=observation,
        external_id=external_id,
        bank_name=bank_name,
        amount=Decimal(amount),
        type=tx_type,
        status=status,
        due_date=due_date,
        category=category,
        paid_at=paid_at,
        credit_card_id=credit_card_id,
    )
    if created_at is not None:
        tx.created_at = created_at
    if updated_at is not None:
        tx.updated_at = updated_at
    db.session.add(tx)
    db.session.commit()
    db.session.refresh(tx)
    return tx


def _make_budget(
    user_id: uuid.UUID,
    *,
    name: str,
    amount: str,
    category: TransactionCategory | None = None,
) -> Budget:
    budget = Budget(
        user_id=user_id,
        name=name,
        amount=Decimal(amount),
        period="monthly",
        category=category.value if category else None,
        is_active=True,
    )
    db.session.add(budget)
    db.session.commit()
    return budget


def _make_credit_card(
    user_id: uuid.UUID,
    *,
    name: str = "Cartão principal",
    limit_amount: str = "1000.00",
    closing_day: int = 20,
    due_day: int = 28,
) -> CreditCard:
    card = CreditCard(
        user_id=user_id,
        name=name,
        limit_amount=Decimal(limit_amount),
        closing_day=closing_day,
        due_day=due_day,
    )
    db.session.add(card)
    db.session.commit()
    return card


def _make_goal(
    user_id: uuid.UUID,
    *,
    title: str,
    current_amount: str,
    target_amount: str,
    target_date: date | None = None,
) -> Goal:
    goal = Goal(
        user_id=user_id,
        title=title,
        current_amount=Decimal(current_amount),
        target_amount=Decimal(target_amount),
        target_date=target_date,
        status="active",
    )
    db.session.add(goal)
    db.session.commit()
    return goal


def _make_goal_contribution(
    user_id: uuid.UUID,
    goal_id: uuid.UUID,
    *,
    amount: str,
    created_at: datetime,
) -> GoalContribution:
    contribution = GoalContribution(
        user_id=user_id,
        goal_id=goal_id,
        amount=Decimal(amount),
        created_at=created_at,
    )
    db.session.add(contribution)
    db.session.commit()
    return contribution


def _make_wallet(
    user_id: uuid.UUID,
    *,
    name: str = "Tesouro Selic",
    value: str = "5000.00",
    asset_class: str = "fixed_income",
) -> Wallet:
    wallet = Wallet(
        user_id=user_id,
        name=name,
        value=Decimal(value),
        estimated_value_on_create_date=Decimal(value),
        asset_class=asset_class,
        annual_rate=Decimal("12.00"),
        register_date=date(2026, 1, 1),
        should_be_on_wallet=True,
    )
    db.session.add(wallet)
    db.session.commit()
    return wallet


def _as_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


class TestFinancialInsightContextBuilderDaily:
    def test_daily_snapshot_includes_pending_expenses_created_today_even_when_due_later(
        self, app
    ) -> None:
        with app.app_context():
            user_id = _make_user()
            anchor = date(2026, 5, 26)
            for index, amount in enumerate(("120.25", "2580.00", "45.90"), start=1):
                _make_transaction(
                    user_id,
                    title=f"Dívida nova {index}",
                    amount=amount,
                    tx_type=TransactionType.EXPENSE,
                    status=TransactionStatus.PENDING,
                    due_date=date(2026, 6, index),
                    created_at=datetime(2026, 5, 26, 9 + index, 0, 0),
                )

            snapshot = FinancialInsightContextBuilder().build_daily(
                user_id=user_id,
                anchor_date=anchor,
            )

        created_today = snapshot["current_period"]["created_today"]
        assert created_today["transaction_count"] == 3
        assert created_today["expense_total"] == "2746.15"
        assert created_today["pending_expense_total"] == "2746.15"
        assert [item["title"] for item in created_today["items"]] == [
            "Dívida nova 1",
            "Dívida nova 2",
            "Dívida nova 3",
        ]
        assert snapshot["transactions"]["included_count"] == 3
        assert snapshot["data_quality"]["domain_presence"]["transactions"] is True

    def test_daily_snapshot_compares_today_yesterday_previous_month_and_mtd(
        self, app
    ) -> None:
        with app.app_context():
            user_id = _make_user()
            anchor = date(2026, 5, 17)
            _make_transaction(
                user_id,
                title="Salário",
                amount="1000.00",
                tx_type=TransactionType.INCOME,
                status=TransactionStatus.PAID,
                due_date=anchor,
            )
            _make_transaction(
                user_id,
                title="Mercado",
                amount="250.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=anchor,
                category=TransactionCategory.alimentacao,
            )
            _make_transaction(
                user_id,
                title="Conta pendente",
                amount="80.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PENDING,
                due_date=anchor,
            )
            _make_transaction(
                user_id,
                title="Conta vencida",
                amount="33.25",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.OVERDUE,
                due_date=anchor,
            )
            _make_transaction(
                user_id,
                title="Despesa cancelada",
                amount="999.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.CANCELLED,
                due_date=anchor,
            )
            _make_transaction(
                user_id,
                title="Ontem mercado",
                amount="400.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 5, 16),
            )
            _make_transaction(
                user_id,
                title="Dia mês passado",
                amount="100.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 4, 17),
            )
            _make_transaction(
                user_id,
                title="Receita mês passado",
                amount="500.00",
                tx_type=TransactionType.INCOME,
                status=TransactionStatus.PAID,
                due_date=date(2026, 4, 17),
            )
            _make_transaction(
                user_id,
                title="Gasto do mês",
                amount="50.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 5, 1),
            )
            _make_transaction(
                user_id,
                title="Receita do mês",
                amount="234.00",
                tx_type=TransactionType.INCOME,
                status=TransactionStatus.PAID,
                due_date=date(2026, 5, 1),
            )

            snapshot = FinancialInsightContextBuilder().build_daily(
                user_id=user_id,
                anchor_date=anchor,
            )

        assert snapshot["schema_version"] == "financial_insight_snapshot.v1"
        assert snapshot["period_type"] == "daily"
        assert snapshot["period"] == {
            "start": "2026-05-17",
            "end": "2026-05-17",
            "label": "2026-05-17",
        }
        assert snapshot["current_period"]["paid"] == {
            "income_total": "1000.00",
            "expense_total": "250.00",
            "balance": "750.00",
            "transaction_count": 2,
        }
        assert snapshot["current_period"]["commitments"]["pending_expense_total"] == (
            "80.00"
        )
        assert snapshot["current_period"]["commitments"]["overdue_expense_total"] == (
            "33.25"
        )
        assert snapshot["current_period"]["commitments"]["transaction_count"] == 2
        assert snapshot["current_period"]["cancelled_transaction_count"] == 1
        assert snapshot["comparisons"]["yesterday"]["paid"]["expense_total"] == (
            "400.00"
        )
        assert snapshot["comparisons"]["yesterday"]["delta"]["expense_total"] == (
            "-150.00"
        )
        assert (
            snapshot["comparisons"]["same_day_previous_month"]["paid"]["income_total"]
            == "500.00"
        )
        assert (
            snapshot["comparisons"]["same_day_previous_month"]["delta"]["income_total"]
            == "500.00"
        )
        assert (
            snapshot["comparisons"]["month_to_date"]["paid"]["expense_total"]
            == "700.00"
        )
        assert "week_to_date_vs_previous_week" in snapshot["comparisons"]

    def test_daily_snapshot_includes_all_financial_domains_and_presence_flags(
        self, app
    ) -> None:
        with app.app_context():
            user_id = _make_user()
            anchor = date(2026, 5, 17)
            card = _make_credit_card(user_id, limit_amount="3000.00")
            _make_transaction(
                user_id,
                title="Mercado",
                amount="250.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=anchor,
                category=TransactionCategory.alimentacao,
            )
            _make_transaction(
                user_id,
                title="Compra no cartão",
                amount="500.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PENDING,
                due_date=anchor,
                credit_card_id=card.id,
            )
            _make_budget(
                user_id,
                name="Mercado",
                amount="1000.00",
                category=TransactionCategory.alimentacao,
            )
            goal = _make_goal(
                user_id,
                title="Reserva",
                current_amount="1500.00",
                target_amount="10000.00",
                target_date=date(2027, 5, 17),
            )
            _make_goal_contribution(
                user_id,
                goal.id,
                amount="500.00",
                created_at=datetime(2026, 5, 10, 12, 0, 0),
            )
            _make_wallet(user_id, value="5000.00")

            snapshot = FinancialInsightContextBuilder().build_daily(
                user_id=user_id,
                anchor_date=anchor,
            )

        assert snapshot["insight_contract"]["required_dimensions"] == [
            "general",
            "transactions",
            "credit_cards",
            "goals",
            "budgets",
            "wallet",
        ]
        assert snapshot["budgets"][0]["name"] == "Mercado"
        assert snapshot["goals"][0]["title"] == "Reserva"
        assert snapshot["credit_cards"][0]["name"] == "Cartão principal"
        assert snapshot["wallet"]["total_value"] == "5000.00"
        assert snapshot["data_quality"]["domain_presence"] == {
            "general": True,
            "transactions": True,
            "credit_cards": True,
            "goals": True,
            "budgets": True,
            "wallet": True,
        }
        assert snapshot["data_quality"]["missing_domains"] == []

    def test_daily_snapshot_includes_projections_block(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            anchor = date(2026, 5, 17)
            _make_transaction(
                user_id,
                title="Salário",
                amount="6000.00",
                tx_type=TransactionType.INCOME,
                status=TransactionStatus.PAID,
                due_date=anchor,
            )
            goal = _make_goal(
                user_id,
                title="Reserva",
                current_amount="1500.00",
                target_amount="10000.00",
                target_date=date(2027, 5, 17),
            )
            _make_goal_contribution(
                user_id,
                goal.id,
                amount="500.00",
                created_at=datetime(2026, 5, 10, 12, 0, 0),
            )
            _make_wallet(user_id, value="5000.00")  # annual_rate 12%

            snapshot = FinancialInsightContextBuilder().build_daily(
                user_id=user_id,
                anchor_date=anchor,
            )

        projections = snapshot["projections"]
        assert projections["horizons_months"] == [3, 6, 12]
        assert projections["rate_basis"] == "observed"
        # Wallet R$5.000 @ 12% a.a. → ~R$5.600 em 12 meses.
        assert "wallet" in projections
        assert abs(
            Decimal(projections["wallet"]["horizon_12m"]) - Decimal("5600.00")
        ) < Decimal("5.00")
        assert projections["goals"][0]["title"] == "Reserva"
        assert "horizon_12m_required" in projections["goals"][0]

    def test_daily_snapshot_marks_missing_previous_month_same_day(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            anchor = date(2026, 3, 31)
            _make_transaction(
                user_id,
                title="Receita do dia",
                amount="100.00",
                tx_type=TransactionType.INCOME,
                status=TransactionStatus.PAID,
                due_date=anchor,
            )

            snapshot = FinancialInsightContextBuilder().build_daily(
                user_id=user_id,
                anchor_date=anchor,
            )

        assert snapshot["data_quality"]["domain_presence"] == {
            "general": True,
            "transactions": True,
            "credit_cards": False,
            "goals": False,
            "budgets": False,
            "wallet": False,
        }
        assert snapshot["data_quality"]["missing_domains"] == [
            "credit_cards",
            "goals",
            "budgets",
            "wallet",
        ]
        assert "same_day_previous_month" not in snapshot["comparisons"]
        assert snapshot["data_quality"]["missing_comparison_periods"] == [
            "same_day_previous_month"
        ]

    def test_daily_snapshot_records_user_timezone_and_fallback_quality(
        self, app
    ) -> None:
        with app.app_context():
            user_id = _make_user()
            anchor = date(2026, 5, 21)

            snapshot = FinancialInsightContextBuilder().build_daily(
                user_id=user_id,
                anchor_date=anchor,
                timezone_name="America/Sao_Paulo",
                timezone_fallback=True,
            )

        assert snapshot["timezone"] == "America/Sao_Paulo"
        assert snapshot["anchor_date"] == "2026-05-21"
        assert snapshot["data_quality"]["timezone_fallback"] is True

    def test_snapshot_redacts_user_pii_and_sensitive_transaction_fields(
        self, app
    ) -> None:
        with app.app_context():
            user_id = _make_user()
            _make_transaction(
                user_id,
                title="Consulta CPF 123.456.789-00",
                description="Enviar recibo para ana@example.com",
                observation="Observação privada com telefone 11999998888",
                external_id="bank-secret-123",
                bank_name="Banco Sensível",
                amount="70.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 5, 17),
            )

            snapshot = FinancialInsightContextBuilder().build_daily(
                user_id=user_id,
                anchor_date=date(2026, 5, 17),
            )

        serialized = _as_json(snapshot)
        assert "Ana Cliente" not in serialized
        assert "ana@example.com" not in serialized
        assert "123.456.789-00" not in serialized
        assert "11999998888" not in serialized
        assert "bank-secret-123" not in serialized
        assert "Banco Sensível" not in serialized
        assert "observation" not in serialized
        assert "external_id" not in serialized
        assert "bank_name" not in serialized
        assert snapshot["transactions"]["sample"][0]["title"] == "Consulta CPF [cpf]"

    def test_email_redaction_does_not_use_backtracking_regex(self) -> None:
        source = getsource(financial_insight_context_builder)

        assert "_EMAIL_RE" not in source
        assert r"(?:\.[\w-]+)+" not in source

        assert (
            financial_insight_context_builder._sanitize_text(
                "Enviar para <ana@example.com>, cópia pix:financeiro+pix@example.com"
            )
            == "Enviar para <[email]>, cópia pix:[email]"
        )


class TestFinancialInsightContextBuilderWeekly:
    def test_weekly_snapshot_summarizes_day_extremes_and_previous_week(
        self, app
    ) -> None:
        with app.app_context():
            user_id = _make_user()
            anchor = date(2026, 5, 13)  # Wednesday, ISO week starts 2026-05-11
            _make_transaction(
                user_id,
                title="Segunda gasto",
                amount="100.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 5, 11),
                category=TransactionCategory.transporte,
            )
            _make_transaction(
                user_id,
                title="Segunda receita",
                amount="10.00",
                tx_type=TransactionType.INCOME,
                status=TransactionStatus.PAID,
                due_date=date(2026, 5, 11),
            )
            _make_transaction(
                user_id,
                title="Terça gasto",
                amount="500.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 5, 12),
                category=TransactionCategory.alimentacao,
            )
            _make_transaction(
                user_id,
                title="Quarta receita",
                amount="1000.00",
                tx_type=TransactionType.INCOME,
                status=TransactionStatus.PAID,
                due_date=date(2026, 5, 13),
            )
            _make_transaction(
                user_id,
                title="Domingo gasto",
                amount="50.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 5, 17),
                category=TransactionCategory.lazer,
            )
            _make_transaction(
                user_id,
                title="Semana anterior",
                amount="200.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 5, 5),
            )

            snapshot = FinancialInsightContextBuilder().build_weekly(
                user_id=user_id,
                anchor_date=anchor,
            )

        assert snapshot["period_type"] == "weekly"
        assert snapshot["period"]["start"] == "2026-05-11"
        assert snapshot["period"]["end"] == "2026-05-17"
        assert len(snapshot["daily_series"]) == 7
        assert snapshot["current_period"]["paid"]["expense_total"] == "650.00"
        assert (
            snapshot["comparisons"]["previous_period"]["paid"]["expense_total"]
            == "200.00"
        )
        assert snapshot["extremes"]["max_expense_day"] == {
            "date": "2026-05-12",
            "amount": "500.00",
        }
        assert snapshot["extremes"]["min_expense_day_with_activity"] == {
            "date": "2026-05-17",
            "amount": "50.00",
        }
        assert snapshot["extremes"]["max_income_day"] == {
            "date": "2026-05-13",
            "amount": "1000.00",
        }
        assert snapshot["extremes"]["min_income_day_with_activity"] == {
            "date": "2026-05-11",
            "amount": "10.00",
        }
        assert snapshot["categories"]["top_expense_categories"][0] == {
            "category": "alimentacao",
            "total": "500.00",
        }


class TestFinancialInsightContextBuilderMonthly:
    def test_monthly_snapshot_tracks_competence_totals_and_generation_deltas(
        self, app
    ) -> None:
        with app.app_context():
            user_id = _make_user()
            anchor = date(2026, 5, 17)
            previous_generated_at = datetime(2026, 5, 10, 12, 0, 0)

            _make_transaction(
                user_id,
                title="Receita maio",
                amount="27934.00",
                tx_type=TransactionType.INCOME,
                status=TransactionStatus.PAID,
                due_date=date(2026, 5, 5),
                created_at=datetime(2026, 5, 1, 9, 0, 0),
                updated_at=datetime(2026, 5, 1, 9, 0, 0),
                paid_at=datetime(2026, 5, 5, 9, 0, 0),
            )
            _make_transaction(
                user_id,
                title="Despesa paga nova",
                amount="21125.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 5, 11),
                created_at=datetime(2026, 5, 11, 8, 0, 0),
                updated_at=datetime(2026, 5, 11, 8, 0, 0),
                paid_at=datetime(2026, 5, 11, 8, 30, 0),
            )
            _make_transaction(
                user_id,
                title="Pendência alterada",
                amount="2730.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PENDING,
                due_date=date(2026, 5, 20),
                created_at=datetime(2026, 5, 2, 10, 0, 0),
                updated_at=datetime(2026, 5, 12, 10, 0, 0),
            )

            snapshot = FinancialInsightContextBuilder().build_monthly(
                user_id=user_id,
                anchor_date=anchor,
                previous_generated_at=previous_generated_at,
            )

        assert snapshot["current_period"]["paid"] == {
            "income_total": "27934.00",
            "expense_total": "21125.00",
            "balance": "6809.00",
            "transaction_count": 2,
        }
        assert (
            snapshot["current_period"]["commitments"]["pending_expense_total"]
            == "2730.00"
        )

        deltas = snapshot["transactions"]["changes_since_last_generation"]
        assert deltas["since"] == "2026-05-10T12:00:00"
        assert deltas["has_changes"] is True
        assert deltas["created"]["count"] == 1
        assert deltas["created"]["expense_total"] == "21125.00"
        assert deltas["updated"]["count"] == 1
        assert deltas["updated"]["expense_total"] == "2730.00"
        assert deltas["paid"]["count"] == 1
        assert deltas["paid"]["expense_total"] == "21125.00"
        assert deltas["created"]["items"][0]["title"] == "Despesa paga nova"
        for section in ("created", "updated", "paid"):
            for item in deltas[section]["items"]:
                assert "id" not in item

    def test_monthly_snapshot_includes_day_extremes_budgets_and_goals(
        self, app
    ) -> None:
        with app.app_context():
            user_id = _make_user()
            anchor = date(2026, 5, 17)
            _make_transaction(
                user_id,
                title="Maior gasto",
                amount="1000.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 5, 2),
                category=TransactionCategory.alimentacao,
            )
            _make_transaction(
                user_id,
                title="Menor gasto",
                amount="100.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 5, 7),
                category=TransactionCategory.transporte,
            )
            _make_transaction(
                user_id,
                title="Maior receita",
                amount="2000.00",
                tx_type=TransactionType.INCOME,
                status=TransactionStatus.PAID,
                due_date=date(2026, 5, 20),
            )
            _make_transaction(
                user_id,
                title="Menor receita",
                amount="300.00",
                tx_type=TransactionType.INCOME,
                status=TransactionStatus.PAID,
                due_date=date(2026, 5, 3),
            )
            _make_budget(
                user_id,
                name="Alimentação",
                amount="800.00",
                category=TransactionCategory.alimentacao,
            )
            _make_goal(
                user_id,
                title="Comprar carro",
                current_amount="1200.00",
                target_amount="5000.00",
                target_date=date(2026, 12, 31),
            )

            snapshot = FinancialInsightContextBuilder().build_monthly(
                user_id=user_id,
                anchor_date=anchor,
            )

        assert snapshot["period_type"] == "monthly"
        assert snapshot["period"]["start"] == "2026-05-01"
        assert snapshot["period"]["end"] == "2026-05-31"
        assert len(snapshot["daily_series"]) == 31
        assert snapshot["current_period"]["paid"] == {
            "income_total": "2300.00",
            "expense_total": "1100.00",
            "balance": "1200.00",
            "transaction_count": 4,
        }
        assert snapshot["extremes"]["max_expense_day"] == {
            "date": "2026-05-02",
            "amount": "1000.00",
        }
        assert snapshot["extremes"]["min_expense_day_with_activity"] == {
            "date": "2026-05-07",
            "amount": "100.00",
        }
        assert snapshot["extremes"]["max_income_day"] == {
            "date": "2026-05-20",
            "amount": "2000.00",
        }
        assert snapshot["extremes"]["min_income_day_with_activity"] == {
            "date": "2026-05-03",
            "amount": "300.00",
        }
        assert snapshot["budgets"] == [
            {
                "name": "Alimentação",
                "category": "alimentacao",
                "period": "monthly",
                "amount": "800.00",
                "spent": "1000.00",
                "utilization_pct": "125.00",
                "exceeded": True,
            }
        ]
        assert len(snapshot["goals"]) == 1
        goal = snapshot["goals"][0]
        assert goal["title"] == "Comprar carro"
        assert goal["current_amount"] == "1200.00"
        assert goal["target_amount"] == "5000.00"
        assert goal["progress_pct"] == "24.00"
        assert goal["target_date"] == "2026-12-31"
        assert goal["remaining_amount"] == "3800.00"
        assert goal["days_remaining"] == 214
        assert goal["required_monthly_pace"] == "475.00"
        assert goal["observed_monthly_pace_90d"] == "0.00"
        assert goal["pace_assessment"] == "insufficient_data"
        assert goal["pace_basis"] == "no_contribution_history"

    def test_monthly_snapshot_includes_deterministic_health_and_risk_flags(
        self, app
    ) -> None:
        with app.app_context():
            user_id = _make_user()
            anchor = date(2026, 5, 17)
            card = _make_credit_card(user_id, limit_amount="1000.00")
            _make_budget(
                user_id,
                name="Alimentação",
                amount="1000.00",
                category=TransactionCategory.alimentacao,
            )
            _make_transaction(
                user_id,
                title="Receita baixa",
                amount="500.00",
                tx_type=TransactionType.INCOME,
                status=TransactionStatus.PAID,
                due_date=date(2026, 5, 2),
            )
            _make_transaction(
                user_id,
                title="Mercado alto",
                amount="1200.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 5, 10),
                category=TransactionCategory.alimentacao,
            )
            _make_transaction(
                user_id,
                title="Fatura do ciclo",
                amount="850.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PENDING,
                due_date=date(2026, 5, 25),
                credit_card_id=card.id,
            )
            _make_transaction(
                user_id,
                title="Boleto vencido",
                amount="100.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.OVERDUE,
                due_date=date(2026, 5, 11),
            )

            snapshot = FinancialInsightContextBuilder().build_monthly(
                user_id=user_id,
                anchor_date=anchor,
            )

        health = snapshot["financial_health"]
        assert health["score"] == 0
        assert health["grade"] == "critical"
        codes = {flag["code"] for flag in health["risk_flags"]}
        assert {
            "negative_paid_balance",
            "overdue_expenses",
            "future_commitment_pressure",
            "budget_exceeded",
            "high_credit_card_utilization",
        }.issubset(codes)
        assert snapshot["data_quality"]["insufficient_financial_health_data"] is False

    def test_weekly_goal_pace_uses_deadline_and_contribution_history(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            anchor = date(2026, 5, 17)
            goal = _make_goal(
                user_id,
                title="Reserva",
                current_amount="1200.00",
                target_amount="5000.00",
                target_date=date(2026, 12, 31),
            )
            _make_goal_contribution(
                user_id,
                goal.id,
                amount="300.00",
                created_at=datetime(2026, 5, 10, 10, 0, 0),
            )
            _make_goal_contribution(
                user_id,
                goal.id,
                amount="150.00",
                created_at=datetime(2026, 4, 20, 10, 0, 0),
            )
            _make_goal_contribution(
                user_id,
                goal.id,
                amount="999.00",
                created_at=datetime(2026, 1, 1, 10, 0, 0),
            )

            snapshot = FinancialInsightContextBuilder().build_weekly(
                user_id=user_id,
                anchor_date=anchor,
            )

        assert len(snapshot["goals"]) == 1
        goal_payload = snapshot["goals"][0]
        assert goal_payload["remaining_amount"] == "3800.00"
        assert goal_payload["days_remaining"] == 228
        assert goal_payload["required_monthly_pace"] == "475.00"
        assert goal_payload["observed_monthly_pace_90d"] == "150.00"
        assert goal_payload["pace_assessment"] == "behind"
        assert goal_payload["pace_basis"] == "goal_total_and_90d_contributions"
        assert snapshot["data_quality"]["insufficient_goal_pace_data"] is False

    def test_weekly_snapshot_marks_insufficient_data_without_transactions_or_goal_pace(
        self, app
    ) -> None:
        with app.app_context():
            user_id = _make_user()
            _make_goal(
                user_id,
                title="Meta sem prazo",
                current_amount="0.00",
                target_amount="1000.00",
                target_date=None,
            )

            snapshot = FinancialInsightContextBuilder().build_weekly(
                user_id=user_id,
                anchor_date=date(2026, 5, 17),
            )

        assert snapshot["financial_health"]["score"] == 50
        assert snapshot["financial_health"]["grade"] == "insufficient_data"
        assert snapshot["financial_health"]["risk_flags"][0]["code"] == (
            "insufficient_transaction_data"
        )
        assert snapshot["data_quality"]["insufficient_financial_health_data"] is True
        assert snapshot["data_quality"]["insufficient_goal_pace_data"] is True
        assert snapshot["goals"][0]["pace_assessment"] == "insufficient_data"
        assert snapshot["goals"][0]["pace_basis"] == "missing_target_date"


class TestWalletValuationSnapshot:
    """Wallet section sourced from PortfolioValuationService (#1546).

    The AI snapshot used to sum the raw nullable ``Wallet.value`` column,
    collapsing ticker holdings (value=NULL) to R$0,00 and hallucinating
    "carteira sem rentabilidade".
    """

    @staticmethod
    def _make_ticker_wallet(user_id: uuid.UUID, *, quantity: str = "5") -> Wallet:
        wallet = Wallet(
            user_id=user_id,
            name="PETR4",
            value=None,
            ticker="PETR4",
            quantity=int(quantity),
            asset_class="stock",
            register_date=date(2026, 1, 1),
            should_be_on_wallet=True,
        )
        db.session.add(wallet)
        db.session.commit()
        return wallet

    def test_ticker_holdings_use_market_valuation(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            self._make_ticker_wallet(user_id, quantity="5")

            with patch(
                "app.services.portfolio_valuation_service."
                "InvestmentService.get_market_price",
                return_value=10.0,
            ):
                snapshot = FinancialInsightContextBuilder().build_daily(
                    user_id=user_id,
                    anchor_date=date(2026, 7, 10),
                )

        wallet = snapshot["wallet"]
        assert wallet["total_current_value"] == "50.00"
        assert wallet["total_value"] == "50.00"  # compat alias
        assert wallet["data_quality"]["market_data_unavailable"] is False
        item = wallet["items"][0]
        assert item["current_value"] == "50.00"
        assert item["valuation_source"] == "brapi_market_price"
        assert "profit_loss_percent" in item

    def test_market_unavailable_sets_data_quality_flag(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            self._make_ticker_wallet(user_id)

            with patch(
                "app.services.portfolio_valuation_service."
                "InvestmentService.get_market_price",
                return_value=None,
            ):
                snapshot = FinancialInsightContextBuilder().build_daily(
                    user_id=user_id,
                    anchor_date=date(2026, 7, 10),
                )

        wallet = snapshot["wallet"]
        assert wallet["data_quality"]["market_data_unavailable"] is True
        assert (
            "wallet_market_prices"
            in (snapshot["data_quality"]["missing_external_rates"])
        )

    def test_distribution_uses_real_values(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            # Manual fixed-income style holding worth 50.00 (value column)…
            _make_wallet(user_id, name="CDB Banco", value="50.00", asset_class="cdb")
            # …plus a ticker holding worth 50.00 only at market price.
            self._make_ticker_wallet(user_id, quantity="5")

            with patch(
                "app.services.portfolio_valuation_service."
                "InvestmentService.get_market_price",
                return_value=10.0,
            ):
                snapshot = FinancialInsightContextBuilder().build_daily(
                    user_id=user_id,
                    anchor_date=date(2026, 7, 10),
                )

        distribution = snapshot["wallet"]["distribution"]
        # Before #1546 the ticker leg valued 0 → 100% fixed income.
        assert Decimal(distribution["market_pct"]) > Decimal("30")
        assert Decimal(distribution["fixed_income_pct"]) < Decimal("70")
        assert snapshot["wallet"]["total_invested_amount"] != "0.00"
