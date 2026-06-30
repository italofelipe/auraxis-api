"""TDD tests for weekly summary and recap enrichment (#1241, #1242).

Coverage (#1241 — weekly):
- _build_weekly_top_categories returns top N categories by spend
- _build_weekly_budget_snapshot returns pro-rata utilization per category budget
- _build_weekly_goals_snapshot returns contributions made this week per goal
- _build_weekly_summary_prompt includes all sections when data present

Coverage (#1242 — recap):
- _build_monthly_goals_evolution returns total contributions per goal in period
- _build_savings_rate_context returns rate vs benchmark
- _build_monthly_budget_by_category returns per-category utilization
- _build_spending_prompt with is_recap=True includes extra sections
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest

from app.extensions.database import db
from app.models.budget import Budget
from app.models.goal import Goal
from app.models.goal_contribution import GoalContribution
from app.models.transaction import (
    Transaction,
    TransactionCategory,
    TransactionStatus,
    TransactionType,
)
from app.services.ai_advisory_service import (
    _build_monthly_budget_by_category,
    _build_monthly_goals_evolution,
    _build_savings_rate_context,
    _build_spending_prompt,
    _build_weekly_budget_snapshot,
    _build_weekly_goals_snapshot,
    _build_weekly_summary_prompt,
    _build_weekly_top_categories,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register_and_login(client, prefix: str = "ai-wk") -> tuple[str, uuid.UUID]:
    suffix = uuid.uuid4().hex[:8]
    email = f"{prefix}-{suffix}@test.com"
    client.post(
        "/auth/register",
        json={"name": prefix, "email": email, "password": "StrongPass@123"},
    )
    login = client.post(
        "/auth/login", json={"email": email, "password": "StrongPass@123"}
    )
    token = login.get_json()["token"]
    from flask_jwt_extended import decode_token

    user_id = uuid.UUID(decode_token(token)["sub"])
    return token, user_id


def _make_tx(
    app,
    user_id: uuid.UUID,
    *,
    amount: float,
    category: TransactionCategory | None = None,
    due_date: date | None = None,
    tx_type: TransactionType = TransactionType.EXPENSE,
) -> None:
    with app.app_context():
        db.session.add(
            Transaction(
                user_id=user_id,
                title="tx",
                amount=Decimal(str(amount)),
                type=tx_type,
                status=TransactionStatus.PAID,
                due_date=due_date or date.today(),
                category=category,
            )
        )
        db.session.commit()


def _make_budget_cat(
    app,
    user_id: uuid.UUID,
    *,
    category: str,
    amount: float = 800.0,
) -> None:
    with app.app_context():
        db.session.add(
            Budget(
                user_id=user_id,
                name=f"Budget {category}",
                amount=Decimal(str(amount)),
                period="monthly",
                is_active=True,
                category=category,
            )
        )
        db.session.commit()


def _make_goal_with_contribution(
    app,
    user_id: uuid.UUID,
    *,
    title: str,
    contribution_amount: float,
    days_ago: int = 2,
) -> uuid.UUID:
    with app.app_context():
        goal = Goal(
            user_id=user_id,
            title=title,
            target_amount=Decimal("5000"),
            current_amount=Decimal(str(contribution_amount)),
            status="active",
        )
        db.session.add(goal)
        db.session.flush()
        db.session.add(
            GoalContribution(
                goal_id=goal.id,
                user_id=user_id,
                amount=Decimal(str(contribution_amount)),
                # Anchor to local midday so the timestamp stays inside the
                # `date.today()`-based windows the tests build, regardless of the
                # local-vs-UTC offset (utcnow() drifts to the next day in the
                # evening in UTC-3, falling outside week_end on Mondays).
                created_at=datetime.combine(
                    date.today() - timedelta(days=days_ago), time(hour=12)
                ),
            )
        )
        db.session.commit()
        return goal.id


# ---------------------------------------------------------------------------
# Tests: _build_weekly_top_categories
# ---------------------------------------------------------------------------


class TestBuildWeeklyTopCategories:
    def test_returns_empty_when_no_transactions(self, app, client):
        _, user_id = _register_and_login(client)
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        with app.app_context():
            result = _build_weekly_top_categories(
                user_id=user_id,
                week_start=week_start,
                week_end=week_start + timedelta(days=6),
            )
        assert result == []

    def test_returns_top_categories_by_spend(self, app, client):
        _, user_id = _register_and_login(client)
        today = date.today()
        week_start = today - timedelta(days=today.weekday())

        _make_tx(
            app,
            user_id,
            amount=300,
            category=TransactionCategory.alimentacao,
            due_date=week_start,
        )
        _make_tx(
            app,
            user_id,
            amount=150,
            category=TransactionCategory.transporte,
            due_date=week_start,
        )
        _make_tx(
            app,
            user_id,
            amount=200,
            category=TransactionCategory.alimentacao,
            due_date=week_start,
        )

        with app.app_context():
            result = _build_weekly_top_categories(
                user_id=user_id,
                week_start=week_start,
                week_end=week_start + timedelta(days=6),
            )

        assert len(result) >= 1
        assert result[0]["category"] == "alimentacao"
        assert result[0]["total"] == pytest.approx(500.0)

    def test_excludes_untagged_transactions_from_top(self, app, client):
        _, user_id = _register_and_login(client)
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        _make_tx(app, user_id, amount=999, category=None, due_date=week_start)
        _make_tx(
            app,
            user_id,
            amount=100,
            category=TransactionCategory.lazer,
            due_date=week_start,
        )

        with app.app_context():
            result = _build_weekly_top_categories(
                user_id=user_id,
                week_start=week_start,
                week_end=week_start + timedelta(days=6),
            )

        categories = [r["category"] for r in result]
        assert "lazer" in categories
        # None/untagged should not appear as a category entry
        assert None not in categories


# ---------------------------------------------------------------------------
# Tests: _build_weekly_budget_snapshot
# ---------------------------------------------------------------------------


class TestBuildWeeklyBudgetSnapshot:
    def test_returns_empty_when_no_budgets(self, app, client):
        _, user_id = _register_and_login(client)
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        with app.app_context():
            result = _build_weekly_budget_snapshot(
                user_id=user_id,
                week_start=week_start,
                week_end=week_start + timedelta(days=6),
            )
        assert result == []

    def test_returns_prorata_utilization(self, app, client):
        _, user_id = _register_and_login(client)
        today = date.today()
        week_start = today - timedelta(days=today.weekday())

        _make_budget_cat(app, user_id, category="alimentacao", amount=800.0)
        _make_tx(
            app,
            user_id,
            amount=200,
            category=TransactionCategory.alimentacao,
            due_date=week_start,
        )

        with app.app_context():
            result = _build_weekly_budget_snapshot(
                user_id=user_id,
                week_start=week_start,
                week_end=week_start + timedelta(days=6),
            )

        assert len(result) == 1
        r = result[0]
        assert r["category"] == "alimentacao"
        assert r["monthly_budget"] == pytest.approx(800.0)
        assert r["weekly_spent"] == pytest.approx(200.0)
        assert "prorated_limit" in r
        assert "pace_status" in r


# ---------------------------------------------------------------------------
# Tests: _build_weekly_goals_snapshot
# ---------------------------------------------------------------------------


class TestBuildWeeklyGoalsSnapshot:
    def test_returns_contributions_this_week(self, app, client):
        _, user_id = _register_and_login(client)
        # Use days_ago bounded by weekday so the contribution always falls in the
        # current ISO week (Monday→Sunday). On Monday, weekday()==0 → days_ago=0
        # (today). On Tuesday→Sunday, days_ago=1 (yesterday, still this week).
        today = date.today()
        days_ago = min(1, today.weekday())
        _make_goal_with_contribution(
            app,
            user_id,
            title="Viagem",
            contribution_amount=300.0,
            days_ago=days_ago,
        )

        week_start = today - timedelta(days=today.weekday())

        with app.app_context():
            result = _build_weekly_goals_snapshot(
                user_id=user_id, week_start=week_start, week_end=today
            )

        assert len(result) == 1
        assert result[0]["title"] == "Viagem"
        assert result[0]["weekly_contribution"] == pytest.approx(300.0)

    def test_excludes_contributions_from_previous_week(self, app, client):
        _, user_id = _register_and_login(client)
        _make_goal_with_contribution(
            app, user_id, title="Old Goal", contribution_amount=500.0, days_ago=10
        )

        today = date.today()
        week_start = today - timedelta(days=today.weekday())

        with app.app_context():
            result = _build_weekly_goals_snapshot(
                user_id=user_id, week_start=week_start, week_end=today
            )

        # Goal exists but no contribution this week
        assert len(result) == 1
        assert result[0]["weekly_contribution"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Tests: _build_weekly_summary_prompt
# ---------------------------------------------------------------------------


class TestBuildWeeklySummaryPrompt:
    def _summary(self) -> dict:
        return {
            "current_week": {"income": 4000, "expense": 2000, "balance": 2000},
            "previous_week": {"income": 3500, "expense": 1800, "balance": 1700},
            "comparison": {"expense_delta": 200},
            "series": [],
        }

    def test_includes_top_categories_section(self):
        cats = [{"category": "alimentacao", "total": 500.0, "pct": 25.0}]
        prompt = _build_weekly_summary_prompt(
            self._summary(), top_categories=cats, budget_snapshot=[], goals_snapshot=[]
        )
        assert "alimentacao" in prompt
        assert "Top categorias" in prompt or "categorias" in prompt.lower()

    def test_includes_budget_section(self):
        budget = [
            {
                "category": "alimentacao",
                "monthly_budget": 800,
                "weekly_spent": 200,
                "pace_status": "ok",
            }
        ]
        prompt = _build_weekly_summary_prompt(
            self._summary(),
            top_categories=[],
            budget_snapshot=budget,
            goals_snapshot=[],
        )
        assert "alimentacao" in prompt
        assert "orçamento" in prompt.lower() or "budget" in prompt.lower()

    def test_omits_sections_when_empty(self):
        prompt = _build_weekly_summary_prompt(
            self._summary(), top_categories=[], budget_snapshot=[], goals_snapshot=[]
        )
        # Should still work but without category/budget sections
        assert isinstance(prompt, str)
        assert len(prompt) > 50


# ---------------------------------------------------------------------------
# Tests: _build_monthly_goals_evolution
# ---------------------------------------------------------------------------


class TestBuildMonthlyGoalsEvolution:
    def test_returns_contributions_in_period(self, app, client):
        _, user_id = _register_and_login(client)
        _make_goal_with_contribution(
            app, user_id, title="Reserva", contribution_amount=500.0, days_ago=5
        )

        with app.app_context():
            result = _build_monthly_goals_evolution(
                user_id=user_id,
                period_start=date.today() - timedelta(days=30),
                period_end=date.today(),
            )

        assert len(result) == 1
        assert result[0]["title"] == "Reserva"
        assert result[0]["monthly_contributions"] == pytest.approx(500.0)

    def test_excludes_contributions_outside_period(self, app, client):
        _, user_id = _register_and_login(client)
        _make_goal_with_contribution(
            app, user_id, title="Old", contribution_amount=200.0, days_ago=60
        )

        with app.app_context():
            result = _build_monthly_goals_evolution(
                user_id=user_id,
                period_start=date.today() - timedelta(days=30),
                period_end=date.today(),
            )

        assert len(result) == 1
        assert result[0]["monthly_contributions"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Tests: _build_savings_rate_context
# ---------------------------------------------------------------------------


class TestBuildSavingsRateContext:
    def test_returns_none_when_no_income_data(self):
        result = _build_savings_rate_context(
            monthly_income=0.0, total_income=0.0, balance=500.0
        )
        assert result is None

    def test_returns_rate_above_benchmark(self):
        result = _build_savings_rate_context(
            monthly_income=5000.0, total_income=5000.0, balance=1500.0
        )
        assert result is not None
        assert result["actual_rate_pct"] == pytest.approx(30.0)
        assert result["benchmark_pct"] == 20.0
        assert result["assessment"] == "above"

    def test_returns_rate_below_benchmark(self):
        result = _build_savings_rate_context(
            monthly_income=5000.0, total_income=5000.0, balance=500.0
        )
        assert result is not None
        assert result["actual_rate_pct"] == pytest.approx(10.0)
        assert result["assessment"] == "below"


# ---------------------------------------------------------------------------
# Tests: _build_monthly_budget_by_category
# ---------------------------------------------------------------------------


class TestBuildMonthlyBudgetByCategory:
    def test_returns_empty_when_no_category_budgets(self, app, client):
        _, user_id = _register_and_login(client)
        with app.app_context():
            result = _build_monthly_budget_by_category(
                user_id=user_id,
                period_start=date(2026, 5, 1),
                period_end=date(2026, 5, 31),
            )
        assert result == []

    def test_returns_utilization_per_category(self, app, client):
        _, user_id = _register_and_login(client)
        _make_budget_cat(app, user_id, category="alimentacao", amount=800.0)
        _make_tx(
            app,
            user_id,
            amount=600,
            category=TransactionCategory.alimentacao,
            due_date=date(2026, 5, 15),
        )

        with app.app_context():
            result = _build_monthly_budget_by_category(
                user_id=user_id,
                period_start=date(2026, 5, 1),
                period_end=date(2026, 5, 31),
            )

        assert len(result) == 1
        r = result[0]
        assert r["category"] == "alimentacao"
        assert r["budget_amount"] == pytest.approx(800.0)
        assert r["spent"] == pytest.approx(600.0)
        assert r["utilization_pct"] == pytest.approx(75.0)
        assert r["exceeded"] is False

    def test_exceeded_flag_when_over_budget(self, app, client):
        _, user_id = _register_and_login(client)
        _make_budget_cat(app, user_id, category="lazer", amount=200.0)
        _make_tx(
            app,
            user_id,
            amount=350,
            category=TransactionCategory.lazer,
            due_date=date(2026, 5, 10),
        )

        with app.app_context():
            result = _build_monthly_budget_by_category(
                user_id=user_id,
                period_start=date(2026, 5, 1),
                period_end=date(2026, 5, 31),
            )

        assert result[0]["exceeded"] is True


# ---------------------------------------------------------------------------
# Tests: recap prompt includes extra sections
# ---------------------------------------------------------------------------


class TestRecapPromptEnrichment:
    def _snapshot(self) -> dict:
        return {
            "period_start": "2026-05-01",
            "period_end": "2026-05-31",
            "total_expense": 3000.0,
            "total_income": 5000.0,
            "balance": 2000.0,
            "savings_rate_pct": 40.0,
            "transaction_count": 40,
            "top_expenses": [],
        }

    def test_recap_includes_budget_by_category(self):
        budgets = [
            {
                "category": "alimentacao",
                "budget_amount": 800,
                "spent": 700,
                "utilization_pct": 87.5,
                "exceeded": False,
            }
        ]
        prompt = _build_spending_prompt(
            self._snapshot(),
            "2026-05",
            is_recap=True,
            monthly_budget_by_category=budgets,
        )
        assert "alimentacao" in prompt
        assert "saude_orcamento_mensal" in prompt or "orcamento_ultrapassado" in prompt

    def test_recap_includes_goals_evolution(self):
        goals_ev = [
            {"title": "Reserva", "monthly_contributions": 500.0, "progress_pct": 30.0}
        ]
        prompt = _build_spending_prompt(
            self._snapshot(),
            "2026-05",
            is_recap=True,
            monthly_goals_evolution=goals_ev,
        )
        assert "Reserva" in prompt
        assert "conquista_meta" in prompt or "progresso_meta" in prompt

    def test_recap_includes_savings_rate(self):
        sr = {
            "actual_rate_pct": 40.0,
            "benchmark_pct": 20.0,
            "gap_pct": 20.0,
            "assessment": "above",
        }
        prompt = _build_spending_prompt(
            self._snapshot(),
            "2026-05",
            is_recap=True,
            savings_rate_ctx=sr,
        )
        assert (
            "40.0" in prompt
            or "poupança" in prompt.lower()
            or "savings" in prompt.lower()
        )
