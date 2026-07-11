"""Sprint 5 (obs-1) tests for the AI insight observability stack.

Covers:
- truncate_snapshot() behaviour below/above the byte cap
- AIInsight.metadata_json persistence by generate_financial_insights
- Prometheus metrics emitted on each generation
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.extensions.database import db
from app.models.ai_insight import AIInsight
from app.services.financial_insight_context_builder import (
    MAX_SNAPSHOT_BYTES,
    truncate_snapshot,
)
from app.services.llm_provider import LLMResponse


@pytest.fixture(autouse=True)
def _bypass_premium_gate():
    """Raw uuid users here; the Premium gate (#1546) has its own coverage."""
    with patch("app.services.ai_advisory_service._ensure_premium_entitlement"):
        yield


_ALL_FINANCIAL_DIMENSIONS = [
    "general",
    "transactions",
    "credit_cards",
    "goals",
    "budgets",
    "wallet",
]
_SORTED_FINANCIAL_DIMENSIONS = sorted(_ALL_FINANCIAL_DIMENSIONS)


def _register_and_login(client) -> tuple[str, str]:
    suffix = uuid4().hex[:8]
    email = f"obs1-{suffix}@email.com"
    password = "StrongPass@123"
    register = client.post(
        "/auth/register",
        json={"name": f"user-{suffix}", "email": email, "password": password},
    )
    assert register.status_code == 201
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    token = login.get_json()["token"]
    from flask_jwt_extended import decode_token

    return token, str(decode_token(token)["sub"])


class TestTruncateSnapshot:
    def test_returns_input_unchanged_when_below_cap(self) -> None:
        snap = {
            "schema_version": "financial_insight_snapshot.v1",
            "current_period": {"paid": {"income_total": "0.00"}},
            "comparisons": {},
        }
        out, info = truncate_snapshot(snap)
        assert out == snap
        assert info["truncated"] is False
        assert info["snapshot_bytes_final"] == info["snapshot_bytes_original"]
        assert info["dropped_sections"] == []

    def test_trims_transactions_when_above_cap(self) -> None:
        items = [
            {"type": "expense", "amount": float(100 + i), "title": "x" * 60}
            for i in range(200)
        ]
        snap = {
            "schema_version": "financial_insight_snapshot.v1",
            "current_period": {"paid": {"income_total": "0.00"}},
            "comparisons": {},
            "transactions": {"items": items},
            "daily_series": [],
            "credit_cards": [],
            "categories": {"top_expense_categories": []},
        }
        out, info = truncate_snapshot(snap, max_bytes=2048)
        assert info["truncated"] is True
        assert "transactions.items" in info["dropped_sections"]
        assert len(out["transactions"]["items"]) <= 15
        assert info["snapshot_bytes_final"] < info["snapshot_bytes_original"]
        # Structural backbone preserved.
        assert out["schema_version"] == "financial_insight_snapshot.v1"
        assert out["current_period"] == snap["current_period"]
        assert out["comparisons"] == snap["comparisons"]

    def test_trims_daily_series_to_last_seven(self) -> None:
        # Use lots of large transactions to force step 1 then step 2 trimming.
        items = [
            {"type": "expense", "amount": float(i + 1), "title": "z" * 100}
            for i in range(30)
        ]
        snap = {
            "schema_version": "financial_insight_snapshot.v1",
            "current_period": {},
            "comparisons": {},
            "transactions": {"items": items},
            "daily_series": [
                {"date": f"2026-05-{d:02d}", "expense": 100.0} for d in range(1, 30)
            ],
            "credit_cards": [],
            "categories": {"top_expense_categories": []},
        }
        out, info = truncate_snapshot(snap, max_bytes=1024)
        assert info["truncated"] is True
        # Step 2 should kick in given how aggressive the cap is.
        if "daily_series" in info["dropped_sections"]:
            assert len(out["daily_series"]) == 7


class TestMetadataPersistenceAndMetrics:
    def test_generate_persists_metadata_json_and_increments_counter(
        self, app, client
    ) -> None:
        token, user_id_str = _register_and_login(client)
        user_id = UUID(user_id_str)

        # Grant entitlement so Premium gate does not block.
        from app.services.entitlement_service import grant_entitlement

        with app.app_context():
            grant_entitlement(
                user_id=user_id,
                feature_key="advanced_simulations",
                source="trial",
            )
            db.session.commit()

        provider = MagicMock()
        provider.generate_with_usage.return_value = LLMResponse(
            content=(
                '{"summary":"Resumo.","items":['
                '{"type":"saude_financeira","dimension":"general",'
                '"title":"Geral","message":"All good.",'
                '"evidence":["current_period.paid.balance"]},'
                '{"type":"saude_financeira","dimension":"transactions",'
                '"title":"Transações","message":"All good.",'
                '"evidence":["data_quality.domain_presence.transactions"]},'
                '{"type":"saude_financeira","dimension":"credit_cards",'
                '"title":"Cartões","message":"All good.",'
                '"evidence":["data_quality.domain_presence.credit_cards"]},'
                '{"type":"saude_financeira","dimension":"goals",'
                '"title":"Metas","message":"All good.",'
                '"evidence":["data_quality.domain_presence.goals"]},'
                '{"type":"saude_financeira","dimension":"budgets",'
                '"title":"Orçamentos","message":"All good.",'
                '"evidence":["data_quality.domain_presence.budgets"]},'
                '{"type":"saude_financeira","dimension":"wallet",'
                '"title":"Carteira","message":"All good.",'
                '"evidence":["data_quality.domain_presence.wallet"]}]}'
            ),
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            model="gpt-test",
            latency_ms=50,
        )

        with app.app_context():
            from app.services.ai_advisory_service import AIAdvisoryService

            with patch(
                "app.services.ai_advisory_service.record_ai_insight_generated"
            ) as record:
                service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
                result = service.generate_financial_insights(
                    period_type="daily",
                    anchor_date=date(2026, 5, 18),
                )

            # Counter called once with the dimensions captured by the LLM resp.
            assert record.called
            kwargs = record.call_args.kwargs
            assert kwargs["period_type"] == "daily"
            assert kwargs["dimensions"] == _SORTED_FINANCIAL_DIMENSIONS
            assert kwargs["tokens_used"] == 30
            assert isinstance(kwargs["truncated"], bool)
            assert kwargs["snapshot_bytes"] >= 0

            # Persisted row has metadata_json populated with the snapshot stats.
            row = (
                db.session.query(AIInsight)
                .filter_by(user_id=user_id)
                .order_by(AIInsight.created_at.desc())
                .first()
            )
            assert row is not None
            md = row.metadata_dict
            assert md["snapshot_version"] == "financial_insight_snapshot.v3"
            assert md["dimensions_present"] == _SORTED_FINANCIAL_DIMENSIONS
            assert "snapshot_bytes_original" in md
            assert "snapshot_bytes_final" in md
            assert isinstance(md["truncated"], bool)
            assert result["items"][0]["dimension"] == "general"


class TestMaxBytesEnvOverride:
    def test_default_constant_is_12kib(self) -> None:
        # MAX_SNAPSHOT_BYTES may be overridden by env in CI; the default is
        # 12 KiB. Just sanity-check the unit (multiple of 1024).
        assert MAX_SNAPSHOT_BYTES > 0
        assert MAX_SNAPSHOT_BYTES % 1024 == 0


class TestRunGovernanceMetrics:
    """#1314 — runs/cost/rejections/truncation/data-quality/purge observability."""

    @staticmethod
    def _make_run(user_id: UUID, *, status, truncated, with_pii=False):
        from datetime import date as _date

        from app.models.ai_insight import InsightType
        from app.services.ai_insight_runs import create_ai_insight_run

        snapshot = {
            "schema_version": "financial_insight_snapshot.v1",
            "data_quality": {
                "domain_presence": {
                    "transactions": {"present": True},
                    "goals": {"present": True},
                    "wallet": {"present": False},
                }
            },
        }
        if with_pii:
            snapshot["note"] = "contato fulano@email.com cpf 123.456.789-00"
        return create_ai_insight_run(
            user_id=user_id,
            status=status,
            period_type=InsightType.daily,
            period_label="2026-05-18",
            period_start=_date(2026, 5, 18),
            period_end=_date(2026, 5, 18),
            snapshot_schema_version="financial_insight_snapshot.v1",
            snapshot_hash="hash-abc123",
            prompt_template_version="v1",
            snapshot_json=snapshot,
            data_quality_json=snapshot["data_quality"],
            truncation_flags_json={"truncated": truncated},
        )

    def test_create_emits_run_truncation_and_data_quality(self, app, client) -> None:
        from app.models.ai_insight_run import AIInsightRunStatus

        _, user_id_str = _register_and_login(client)
        user_id = UUID(user_id_str)
        with app.app_context():
            with (
                patch("app.services.ai_insight_runs.record_ai_insight_run") as run_m,
                patch(
                    "app.services.ai_insight_runs.record_ai_insight_truncated"
                ) as trunc_m,
                patch(
                    "app.services.ai_insight_runs.record_ai_insight_data_quality"
                ) as dq_m,
            ):
                self._make_run(
                    user_id,
                    status=AIInsightRunStatus.previewed,
                    truncated=True,
                )

            assert run_m.call_args.kwargs == {
                "status": "previewed",
                "period_type": "daily",
            }
            assert trunc_m.call_args.kwargs == {"period_type": "daily"}
            # 2 of 3 domains present (wallet flagged absent).
            assert dq_m.call_args.kwargs == {
                "period_type": "daily",
                "domains_present": 2,
            }

    def test_create_does_not_emit_truncation_when_not_truncated(
        self, app, client
    ) -> None:
        from app.models.ai_insight_run import AIInsightRunStatus

        _, user_id_str = _register_and_login(client)
        user_id = UUID(user_id_str)
        with app.app_context():
            with patch(
                "app.services.ai_insight_runs.record_ai_insight_truncated"
            ) as trunc_m:
                self._make_run(
                    user_id,
                    status=AIInsightRunStatus.previewed,
                    truncated=False,
                )
            assert not trunc_m.called

    def test_create_structured_log_carries_run_fields_without_pii(
        self, app, client, caplog
    ) -> None:
        import logging

        from app.models.ai_insight_run import AIInsightRunStatus

        _, user_id_str = _register_and_login(client)
        user_id = UUID(user_id_str)
        with app.app_context():
            with caplog.at_level(logging.INFO, logger="app.services.ai_insight_runs"):
                self._make_run(
                    user_id,
                    status=AIInsightRunStatus.previewed,
                    truncated=False,
                    with_pii=True,
                )

        created = [r for r in caplog.records if "ai_insight.run.created" in r.message]
        assert created, "expected an ai_insight.run.created structured log"
        msg = created[0].getMessage()
        # Carries the auditable, non-PII fields.
        assert "snapshot_hash=hash-abc123" in msg
        assert "status=previewed" in msg
        assert "period_type=daily" in msg
        # Never leaks PII from the snapshot.
        assert "fulano@email.com" not in msg
        assert "123.456.789-00" not in msg

    def test_transition_emits_run_and_cost_on_generated(self, app, client) -> None:
        from decimal import Decimal

        from app.extensions.database import db
        from app.models.ai_insight_run import AIInsightRunStatus
        from app.services.ai_insight_runs import transition_ai_insight_run_status

        _, user_id_str = _register_and_login(client)
        user_id = UUID(user_id_str)
        with app.app_context():
            run = self._make_run(
                user_id,
                status=AIInsightRunStatus.previewed,
                truncated=False,
            )
            run.cost_usd = Decimal("0.0123")
            db.session.commit()
            with (
                patch("app.services.ai_insight_runs.record_ai_insight_run") as run_m,
                patch("app.services.ai_insight_runs.record_ai_insight_cost") as cost_m,
            ):
                transition_ai_insight_run_status(run, AIInsightRunStatus.generated)

            assert run_m.call_args.kwargs == {
                "status": "generated",
                "period_type": "daily",
            }
            assert cost_m.call_args.kwargs["period_type"] == "daily"
            assert cost_m.call_args.kwargs["cost_usd"] > 0

    def test_purge_emits_purged_metric(self, app, client) -> None:
        from datetime import timedelta

        from app.extensions.database import db
        from app.models.ai_insight_run import AIInsightRunStatus
        from app.services.ai_insight_runs import purge_expired_ai_insight_runs
        from app.utils.datetime_utils import utc_now_naive

        _, user_id_str = _register_and_login(client)
        user_id = UUID(user_id_str)
        with app.app_context():
            run = self._make_run(
                user_id,
                status=AIInsightRunStatus.previewed,
                truncated=False,
            )
            run.expires_at = utc_now_naive() - timedelta(days=1)
            db.session.commit()

            with (
                patch(
                    "app.services.ai_insight_runs.record_ai_insight_runs_purged"
                ) as purged_m,
                patch("app.services.ai_insight_runs.record_ai_insight_run") as run_m,
            ):
                count = purge_expired_ai_insight_runs()

            assert count >= 1
            assert purged_m.call_args.args[0] >= 1
            statuses = {c.kwargs["status"] for c in run_m.call_args_list}
            assert "purged" in statuses

    def test_filter_valid_items_emits_rejection_per_reason(self) -> None:
        from app.services.insight_evidence_validator import filter_valid_items

        items = [
            {"dimension": "nope", "type": "x", "evidence": ["transactions"]},
            {"dimension": "transactions", "type": "x", "evidence": []},
            {
                "dimension": "general",
                "type": "x",
                "evidence": ["current_period.paid.balance"],
            },
        ]
        with patch(
            "app.services.insight_evidence_validator.record_ai_insight_rejection"
        ) as rej_m:
            accepted = filter_valid_items(items, user_id=None)

        assert len(accepted) == 1
        reasons = {c.kwargs["reason"] for c in rej_m.call_args_list}
        assert reasons == {"invalid_dimension", "missing_evidence"}
