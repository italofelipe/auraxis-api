"""Unit tests for the deterministic "Insights Fluida" structured fields (#1501).

The Fluida screen consumes structured data that the backend CALCULATES from the
user's real transactions (the LLM only writes prose; numbers are anchored). These
tests cover the pure builders:

  - build_paragraphs(summary)        — split AI prose into short paragraphs
  - build_retro(user_id, anchor)     — yesterday / day-before / week-vs-week outflow
  - build_series(user_id, anchor)    — daily[7] + weekly[6] outflow sums
  - build_highlights(user_id, anchor)— per-theme highlights (biggest expense, etc.)

All money is decimal (Numeric(12,2)) — never cents. Aggregations exclude
soft-deleted rows and ``impact_policy == CARDS_ONLY`` and only count ``PAID``
transactions on ``due_date``, mirroring weekly_summary / analytics services.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from app.extensions.database import db
from app.models.transaction import (
    Transaction,
    TransactionCategory,
    TransactionImpactPolicy,
    TransactionStatus,
    TransactionType,
)
from app.models.user import User
from app.services.insight_fluida_builder import (
    build_highlights,
    build_paragraphs,
    build_retro,
    build_series,
)


def _make_user() -> uuid.UUID:
    user = User(
        name="Fluida Cliente",
        email=f"fluida-{uuid.uuid4().hex[:8]}@example.com",
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
    impact_policy: TransactionImpactPolicy = TransactionImpactPolicy.FULL,
    deleted: bool = False,
    created_at: datetime | None = None,
) -> Transaction:
    tx = Transaction(
        user_id=user_id,
        title=title,
        description=title,
        amount=Decimal(amount),
        type=tx_type,
        status=status,
        due_date=due_date,
        category=category,
        impact_policy=impact_policy,
        deleted=deleted,
    )
    if created_at is not None:
        tx.created_at = created_at
    db.session.add(tx)
    db.session.commit()
    db.session.refresh(tx)
    return tx


# ---------------------------------------------------------------------------
# build_paragraphs — pure, no DB
# ---------------------------------------------------------------------------


class TestBuildParagraphs:
    def test_splits_on_blank_lines(self) -> None:
        summary = "Primeiro parágrafo.\n\nSegundo parágrafo."
        assert build_paragraphs(summary) == [
            "Primeiro parágrafo.",
            "Segundo parágrafo.",
        ]

    def test_splits_long_single_block_into_sentences(self) -> None:
        summary = (
            "Você gastou bastante esta semana. "
            "O maior gasto foi com alimentação. "
            "Considere revisar o orçamento."
        )
        paragraphs = build_paragraphs(summary)
        assert len(paragraphs) == 3
        assert paragraphs[0] == "Você gastou bastante esta semana."
        assert paragraphs[2] == "Considere revisar o orçamento."

    def test_strips_whitespace_and_drops_empty_chunks(self) -> None:
        summary = "  Um.  \n\n\n   \n\n Dois.  "
        assert build_paragraphs(summary) == ["Um.", "Dois."]

    def test_empty_summary_returns_empty_list(self) -> None:
        assert build_paragraphs("") == []
        assert build_paragraphs("   ") == []


# ---------------------------------------------------------------------------
# build_retro — calculated outflow comparison
# ---------------------------------------------------------------------------


class TestBuildRetro:
    def test_returns_three_entries_with_expected_keys(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            entries = build_retro(user_id=user_id, anchor=date(2026, 6, 15))
        assert [e["key"] for e in entries] == ["yesterday", "daybefore", "vs_week"]
        for entry in entries:
            assert set(entry) == {"key", "label", "value", "caption", "sign"}

    def test_yesterday_and_daybefore_sum_only_expense_outflow(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            anchor = date(2026, 6, 15)
            # Yesterday (2026-06-14): two expenses + one income (income ignored)
            _make_transaction(
                user_id,
                title="ontem-1",
                amount="40.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 6, 14),
            )
            _make_transaction(
                user_id,
                title="ontem-2",
                amount="10.50",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 6, 14),
            )
            _make_transaction(
                user_id,
                title="ontem-income",
                amount="999.00",
                tx_type=TransactionType.INCOME,
                status=TransactionStatus.PAID,
                due_date=date(2026, 6, 14),
            )
            # Day before (2026-06-13): one expense
            _make_transaction(
                user_id,
                title="anteontem-1",
                amount="25.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 6, 13),
            )
            entries = {e["key"]: e for e in build_retro(user_id=user_id, anchor=anchor)}

        assert entries["yesterday"]["value"] == 50.5
        assert entries["daybefore"]["value"] == 25.0

    def test_yesterday_sign_is_negative_when_higher_than_daybefore(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            anchor = date(2026, 6, 15)
            _make_transaction(
                user_id,
                title="ontem",
                amount="80.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 6, 14),
            )
            _make_transaction(
                user_id,
                title="anteontem",
                amount="30.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 6, 13),
            )
            entries = {e["key"]: e for e in build_retro(user_id=user_id, anchor=anchor)}

        # Spending MORE yesterday than the day before is a negative signal.
        assert entries["yesterday"]["sign"] == "neg"

    def test_excludes_cards_only_and_unpaid_and_deleted(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            anchor = date(2026, 6, 15)
            _make_transaction(
                user_id,
                title="valida",
                amount="40.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 6, 14),
            )
            _make_transaction(
                user_id,
                title="cards-only",
                amount="500.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 6, 14),
                impact_policy=TransactionImpactPolicy.CARDS_ONLY,
            )
            _make_transaction(
                user_id,
                title="pending",
                amount="500.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PENDING,
                due_date=date(2026, 6, 14),
            )
            _make_transaction(
                user_id,
                title="deleted",
                amount="500.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 6, 14),
                deleted=True,
            )
            entries = {e["key"]: e for e in build_retro(user_id=user_id, anchor=anchor)}

        assert entries["yesterday"]["value"] == 40.0

    def test_vs_week_sign_neutral_when_no_history(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            entries = {
                e["key"]: e
                for e in build_retro(user_id=user_id, anchor=date(2026, 6, 15))
            }
        assert entries["vs_week"]["sign"] == "neutral"
        assert entries["vs_week"]["value"] == 0.0


# ---------------------------------------------------------------------------
# build_series — calculated daily[7] + weekly[6] outflow
# ---------------------------------------------------------------------------


class TestBuildSeries:
    def test_shape_is_seven_daily_and_six_weekly(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            series = build_series(user_id=user_id, anchor=date(2026, 6, 15))
        assert set(series) == {"daily", "weekly"}
        assert len(series["daily"]) == 7
        assert len(series["weekly"]) == 6
        assert all(isinstance(v, float) for v in series["daily"])
        assert all(isinstance(v, float) for v in series["weekly"])

    def test_daily_buckets_expense_on_correct_day(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            anchor = date(2026, 6, 15)
            # Anchor day (last bucket) gets 100; the day before gets 40.
            _make_transaction(
                user_id,
                title="hoje",
                amount="100.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=anchor,
            )
            _make_transaction(
                user_id,
                title="ontem",
                amount="40.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 6, 14),
            )
            # Income on anchor must NOT appear in an outflow series.
            _make_transaction(
                user_id,
                title="salario",
                amount="5000.00",
                tx_type=TransactionType.INCOME,
                status=TransactionStatus.PAID,
                due_date=anchor,
            )
            series = build_series(user_id=user_id, anchor=anchor)

        # daily[-1] is the anchor day, daily[-2] is the day before.
        assert series["daily"][-1] == 100.0
        assert series["daily"][-2] == 40.0
        assert series["daily"][0] == 0.0

    def test_weekly_last_bucket_sums_anchor_week_outflow(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            # 2026-06-15 is a Monday → anchor week is 06-15..06-21.
            anchor = date(2026, 6, 15)
            _make_transaction(
                user_id,
                title="seg",
                amount="30.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 6, 15),
            )
            _make_transaction(
                user_id,
                title="qua",
                amount="20.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 6, 17),
            )
            series = build_series(user_id=user_id, anchor=anchor)

        assert series["weekly"][-1] == 50.0


# ---------------------------------------------------------------------------
# build_highlights — per-theme calculated highlights
# ---------------------------------------------------------------------------


class TestBuildHighlights:
    def test_includes_biggest_expense_of_month(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            anchor = date(2026, 6, 15)
            _make_transaction(
                user_id,
                title="Aluguel",
                amount="1800.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 6, 5),
                category=TransactionCategory.moradia,
            )
            _make_transaction(
                user_id,
                title="Mercado",
                amount="320.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 6, 7),
                category=TransactionCategory.alimentacao,
            )
            highlights = build_highlights(user_id=user_id, anchor=anchor)

        labels = [h["label"] for h in highlights]
        assert "Maior gasto do mês" in labels
        biggest = next(h for h in highlights if h["label"] == "Maior gasto do mês")
        assert biggest["value"] == 1800.0
        assert biggest["sub"] == "Aluguel"

    def test_includes_single_credit_when_only_one_income(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            anchor = date(2026, 6, 15)
            _make_transaction(
                user_id,
                title="Salário",
                amount="5000.00",
                tx_type=TransactionType.INCOME,
                status=TransactionStatus.PAID,
                due_date=date(2026, 6, 5),
            )
            _make_transaction(
                user_id,
                title="Padaria",
                amount="20.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 6, 7),
            )
            highlights = build_highlights(user_id=user_id, anchor=anchor)

        labels = [h["label"] for h in highlights]
        assert "Único crédito" in labels
        credit = next(h for h in highlights if h["label"] == "Único crédito")
        assert credit["value"] == 5000.0

    def test_each_highlight_has_label_value_sub(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            anchor = date(2026, 6, 15)
            _make_transaction(
                user_id,
                title="Mercado",
                amount="320.00",
                tx_type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=date(2026, 6, 7),
            )
            highlights = build_highlights(user_id=user_id, anchor=anchor)

        assert highlights, "expected at least one highlight"
        assert len(highlights) <= 3
        for h in highlights:
            assert set(h) == {"label", "value", "sub"}

    def test_empty_when_no_transactions(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            highlights = build_highlights(user_id=user_id, anchor=date(2026, 6, 15))
        assert highlights == []

    def test_multiple_incomes_yield_biggest_and_total_credit(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            anchor = date(2026, 6, 15)
            for title, amount, day in (
                ("Salário", "5000.00", 5),
                ("Freela", "1200.00", 9),
                ("Reembolso", "300.00", 11),
            ):
                _make_transaction(
                    user_id,
                    title=title,
                    amount=amount,
                    tx_type=TransactionType.INCOME,
                    status=TransactionStatus.PAID,
                    due_date=date(2026, 6, day),
                )
            highlights = build_highlights(user_id=user_id, anchor=anchor)

        by_label = {h["label"]: h for h in highlights}
        assert "Maior crédito do mês" in by_label
        assert by_label["Maior crédito do mês"]["value"] == 5000.0
        assert by_label["Maior crédito do mês"]["sub"] == "Salário"
        assert "Total de créditos" in by_label
        assert by_label["Total de créditos"]["value"] == 6500.0
        assert by_label["Total de créditos"]["sub"] == "3 entradas"
