"""Snapshot v3 + prompt v3 + mix de modelos (#1547).

Covers the enriched AI snapshot:
- user tags on transaction samples + ``tags`` aggregations (top by expense/income)
- tag-linked budgets included with tag name and tag-scoped spent
- ``pending_commitments``: labelled overdue items + upcoming 7/30d
- ``month_summary``: savings rate, burn rate, projected end-of-month balance
- per-period snapshot byte caps (daily 12KiB; weekly/monthly 24KiB)
- ``_trim_transactions`` handles the real ``sample`` key (was a silent no-op)
- per-period model mix: daily manual → gpt-4o-mini; weekly/monthly → provider default
- prompt v3 mandates sections with numbers and references the new snapshot keys
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.extensions.database import db
from app.models.budget import Budget
from app.models.tag import Tag
from app.models.transaction import (
    Transaction,
    TransactionStatus,
    TransactionType,
)
from app.models.user import User
from app.services.financial_insight_context_builder import (
    FinancialInsightContextBuilder,
    truncate_snapshot,
)
from app.services.llm_provider import LLMResponse

_ANCHOR = date(2026, 7, 10)


@pytest.fixture(autouse=True)
def _bypass_premium_gate():
    """Raw uuid users; the Premium gate (#1546) has dedicated coverage."""
    with patch("app.services.ai_advisory_service._ensure_premium_entitlement"):
        yield


def _make_user() -> uuid.UUID:
    user = User(
        name="Tag Cliente",
        email=f"tags-{uuid.uuid4().hex[:8]}@example.com",
        password="hashed",
    )
    db.session.add(user)
    db.session.commit()
    return user.id


def _make_tag(user_id: uuid.UUID, name: str) -> Tag:
    tag = Tag(user_id=user_id, name=name)
    db.session.add(tag)
    db.session.commit()
    return tag


def _make_tx(
    user_id: uuid.UUID,
    *,
    title: str,
    amount: str,
    tx_type: TransactionType = TransactionType.EXPENSE,
    status: TransactionStatus = TransactionStatus.PAID,
    due_date: date = _ANCHOR,
    tag_id: uuid.UUID | None = None,
) -> Transaction:
    tx = Transaction(
        user_id=user_id,
        title=title,
        description=title,
        amount=Decimal(amount),
        type=tx_type,
        status=status,
        due_date=due_date,
        tag_id=tag_id,
    )
    db.session.add(tx)
    db.session.commit()
    return tx


def _build_daily(user_id: uuid.UUID) -> dict:
    return FinancialInsightContextBuilder().build_daily(
        user_id=user_id,
        anchor_date=_ANCHOR,
    )


class TestTagsInSnapshot:
    def test_sample_items_carry_tag_name(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            academia = _make_tag(user_id, "Academia")
            _make_tx(user_id, title="Mensalidade", amount="120.00", tag_id=academia.id)

            snapshot = _build_daily(user_id)

        sample = snapshot["transactions"]["sample"]
        assert sample[0]["tag"] == "Academia"

    def test_tags_aggregation_top_by_expense_and_income(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            academia = _make_tag(user_id, "Academia")
            freela = _make_tag(user_id, "Freela")
            _make_tx(user_id, title="Plano", amount="120.00", tag_id=academia.id)
            _make_tx(user_id, title="Whey", amount="80.00", tag_id=academia.id)
            _make_tx(
                user_id,
                title="Projeto X",
                amount="900.00",
                tx_type=TransactionType.INCOME,
                tag_id=freela.id,
            )
            _make_tx(user_id, title="Sem tag", amount="50.00")

            snapshot = _build_daily(user_id)

        tags = snapshot["tags"]
        expense_by_tag = {entry["tag"]: entry for entry in tags["top_by_expense"]}
        assert expense_by_tag["Academia"]["total"] == "200.00"
        assert expense_by_tag["Academia"]["count"] == 2
        income_by_tag = {entry["tag"]: entry for entry in tags["top_by_income"]}
        assert income_by_tag["Freela"]["total"] == "900.00"

    def test_tag_budget_included_with_tag_scoped_spent(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            academia = _make_tag(user_id, "Academia")
            db.session.add(
                Budget(
                    user_id=user_id,
                    name="Academia mensal",
                    amount=Decimal("200.00"),
                    period="monthly",
                    tag_id=academia.id,
                    is_active=True,
                )
            )
            db.session.commit()
            _make_tx(user_id, title="Plano", amount="120.00", tag_id=academia.id)
            _make_tx(user_id, title="Outros gastos", amount="500.00")

            snapshot = _build_daily(user_id)

        tagged = [b for b in snapshot["budgets"] if b.get("tag") == "Academia"]
        assert tagged, "tag-linked budget must be present in the snapshot"
        assert tagged[0]["spent"] == "120.00"  # tag-scoped, not the 500.00


class TestPendingCommitments:
    def test_overdue_items_are_labelled_with_days_overdue(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            _make_tx(
                user_id,
                title="Condomínio",
                amount="1400.00",
                status=TransactionStatus.PENDING,
                due_date=date(2026, 7, 6),
            )
            _make_tx(
                user_id,
                title="Fatura Julho",
                amount="12055.51",
                status=TransactionStatus.OVERDUE,
                due_date=date(2026, 7, 5),
            )

            snapshot = _build_daily(user_id)

        overdue = snapshot["pending_commitments"]["overdue"]
        assert overdue["count"] == 2
        titles = {item["title"]: item for item in overdue["items"]}
        assert titles["Condomínio"]["days_overdue"] == 4
        assert titles["Fatura Julho"]["days_overdue"] == 5
        assert overdue["expense_total"] == "13455.51"

    def test_upcoming_windows_split_7d_and_30d(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            _make_tx(
                user_id,
                title="Parcela financiamento",
                amount="2650.00",
                status=TransactionStatus.PENDING,
                due_date=date(2026, 7, 15),  # within 7d
            )
            _make_tx(
                user_id,
                title="Fatura de agosto",
                amount="900.00",
                status=TransactionStatus.PENDING,
                due_date=date(2026, 8, 5),  # within 30d, beyond 7d
            )
            _make_tx(
                user_id,
                title="IPVA distante",
                amount="300.00",
                status=TransactionStatus.PENDING,
                due_date=date(2026, 9, 20),  # beyond 30d — excluded
            )

            snapshot = _build_daily(user_id)

        pending = snapshot["pending_commitments"]
        titles_7d = [item["title"] for item in pending["upcoming_7d"]["items"]]
        titles_30d = [item["title"] for item in pending["upcoming_30d"]["items"]]
        assert titles_7d == ["Parcela financiamento"]
        assert "Fatura de agosto" in titles_30d
        assert "IPVA distante" not in titles_30d
        assert pending["upcoming_30d"]["expense_total"] == "3550.00"


class TestMonthSummary:
    def test_month_summary_fields(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            _make_tx(
                user_id,
                title="Salário BRQ",
                amount="10754.00",
                tx_type=TransactionType.INCOME,
                due_date=date(2026, 7, 1),
            )
            _make_tx(
                user_id, title="Aluguel", amount="5000.00", due_date=date(2026, 7, 4)
            )
            _make_tx(
                user_id,
                title="Parcela",
                amount="2650.00",
                status=TransactionStatus.PENDING,
                due_date=date(2026, 7, 15),
            )

            snapshot = _build_daily(user_id)

        summary = snapshot["month_summary"]
        assert summary["month"] == "2026-07"
        assert summary["income_mtd"] == "10754.00"
        assert summary["expense_mtd"] == "5000.00"
        assert summary["balance_mtd"] == "5754.00"
        assert Decimal(summary["savings_rate_pct"]) > 0
        assert Decimal(summary["burn_rate_daily"]) > 0
        # Commitments-based projection: balance minus pending expenses of the
        # rest of the month.
        assert summary["projected_eom_balance"] == "3104.00"


class TestPerPeriodCapsAndTrim:
    def test_trim_transactions_handles_sample_key(self) -> None:
        from app.services.financial_insight_context_builder import _trim_transactions

        sample = [
            {"type": "expense", "amount": f"{100 + i}.00", "title": f"tx {i}"}
            for i in range(30)
        ]
        snapshot = {"transactions": {"included_count": 30, "sample": sample}}
        assert _trim_transactions(snapshot) is True
        assert len(snapshot["transactions"]["sample"]) <= 15

    def test_snapshot_max_bytes_per_period(self, monkeypatch) -> None:
        from app.services.ai_advisory_service import _snapshot_max_bytes

        monkeypatch.delenv("AI_SNAPSHOT_MAX_BYTES", raising=False)
        monkeypatch.delenv("AI_SNAPSHOT_MAX_BYTES_LONG", raising=False)
        assert _snapshot_max_bytes("daily") == 12 * 1024
        assert _snapshot_max_bytes("weekly") == 24 * 1024
        assert _snapshot_max_bytes("monthly") == 24 * 1024

    def test_truncate_respects_explicit_cap(self) -> None:
        sample = [
            {"type": "expense", "amount": f"{i}.00", "title": "x" * 80}
            for i in range(200)
        ]
        snapshot = {
            "schema_version": "financial_insight_snapshot.v3",
            "current_period": {},
            "comparisons": {},
            "transactions": {"included_count": 200, "sample": sample},
        }
        _, info = truncate_snapshot(snapshot, max_bytes=2048)
        assert info["truncated"] is True
        assert "transactions.items" in info["dropped_sections"]


class TestPerPeriodModelMix:
    @staticmethod
    def _llm_response() -> LLMResponse:
        item = (
            '{"type":"saude_financeira","dimension":"general","title":"Item",'
            '"message":"Os dados foram analisados.",'
            '"evidence":["current_period.paid.balance"]}'
        )
        return LLMResponse(
            content=f'{{"summary":"Resumo.","items":[{item}]}}',
            prompt_tokens=100,
            completion_tokens=40,
            total_tokens=140,
            model="gpt-4o-mini",
            latency_ms=10,
        )

    def test_daily_manual_generation_uses_mini_model(self, app, monkeypatch) -> None:
        monkeypatch.delenv("OPENAI_ADVISORY_MODEL_DAILY", raising=False)
        with app.app_context():
            from app.services.ai_advisory_service import AIAdvisoryService

            user_id = _make_user()
            provider = MagicMock()
            provider.generate_with_usage.return_value = self._llm_response()
            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
            service.generate_financial_insights(
                period_type="daily", anchor_date=_ANCHOR
            )

            assert provider.generate_with_usage.call_args.kwargs["model"] == (
                "gpt-4o-mini"
            )

    def test_weekly_generation_uses_provider_default_model(self, app) -> None:
        with app.app_context():
            from app.services.ai_advisory_service import AIAdvisoryService

            user_id = _make_user()
            provider = MagicMock()
            provider.generate_with_usage.return_value = self._llm_response()
            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
            service.generate_financial_insights(
                period_type="weekly", anchor_date=_ANCHOR
            )

            assert "model" not in provider.generate_with_usage.call_args.kwargs

    def test_openai_provider_accepts_model_override(self, monkeypatch) -> None:
        from app.services.llm_provider import OpenAILLMProvider

        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        provider = OpenAILLMProvider()
        captured: dict = {}

        class _Resp:
            def raise_for_status(self) -> None:
                return None

            @staticmethod
            def json() -> dict:
                return {
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                    "model": "gpt-4o-mini-2024-07-18",
                }

        def _fake_post(url, headers=None, json=None, timeout=None):
            captured["payload"] = json
            return _Resp()

        with patch("requests.post", _fake_post):
            provider.generate_with_usage("prompt", model="gpt-4o-mini")

        assert captured["payload"]["model"] == "gpt-4o-mini"


class TestPromptV3:
    def test_prompt_mandates_sections_and_new_keys(self, app) -> None:
        with app.app_context():
            from app.services.ai_advisory_service import (
                _build_financial_insight_prompt,
            )

            user_id = _make_user()
            _make_tx(user_id, title="Mercado", amount="100.00")
            snapshot = _build_daily(user_id)
            prompt = _build_financial_insight_prompt(
                snapshot, period_type="daily", forecast=False
            )

        for required in (
            "pending_commitments",
            "month_summary",
            "tags.top_by_expense",
            "panorama do período",
            "pendências e vencimentos",
            "recomendações acionáveis",
        ):
            assert required in prompt, f"prompt v3 must mention: {required}"
        # Generic advice without numbers is forbidden explicitly.
        assert "número" in prompt


class TestSnapshotVersionBump:
    def test_schema_version_is_v3(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            snapshot = _build_daily(user_id)
        assert snapshot["schema_version"] == "financial_insight_snapshot.v3"
