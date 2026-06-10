"""Automatic end-of-month recap batch (#1386, slice B).

Covers generate_monthly_recaps_for_all: eligibility (users with activity in the
month that just ended), idempotency, and recap persistence.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal

from app.extensions.database import db
from app.models.ai_insight import AIInsight, InsightType
from app.models.user import User
from app.services.ai_monthly_report_service import generate_monthly_recaps_for_all
from app.services.llm_provider import LLMResponse


def _create_user() -> uuid.UUID:
    user = User(
        name="Recap Tester",
        email=f"recap-{uuid.uuid4().hex[:8]}@email.com",
        password="hash",
    )
    db.session.add(user)
    db.session.commit()
    return user.id


def _seed_daily_insight(user_id: uuid.UUID, *, period: date) -> None:
    db.session.add(
        AIInsight(
            user_id=user_id,
            content=json.dumps(
                {
                    "summary": "Daily",
                    "items": [
                        {
                            "type": "saude_financeira",
                            "dimension": "general",
                            "title": "Resumo",
                            "message": "Dia consolidado.",
                            "evidence": ["current_period.paid.balance"],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            insight_type=InsightType.daily,
            period_label=period.isoformat(),
            period_start=period,
            period_end=period,
            model="gpt-test",
            tokens_used=50,
            cost_usd=Decimal("0.00001"),
        )
    )
    db.session.commit()


def _seed_monthly_recap(user_id: uuid.UUID, *, period_label: str) -> None:
    start = date.fromisoformat(f"{period_label}-01")
    db.session.add(
        AIInsight(
            user_id=user_id,
            content="{}",
            insight_type=InsightType.monthly,
            period_label=period_label,
            period_start=start,
            period_end=start,
            model="gpt-test",
            tokens_used=10,
            cost_usd=Decimal("0.00001"),
        )
    )
    db.session.commit()


class _RecapProvider:
    def generate_with_usage(
        self, prompt: str, response_schema=None, max_tokens=None
    ) -> LLMResponse:
        dimensions = [
            "general",
            "transactions",
            "goals",
            "budgets",
            "credit_cards",
            "wallet",
        ]
        return LLMResponse(
            content=json.dumps(
                {
                    "summary": "Recap mensal consolidado.",
                    "items": [
                        {
                            "type": "saude_financeira",
                            "dimension": dim,
                            "title": dim,
                            "message": "Consolidado do mês.",
                            "evidence": [
                                f"data_quality.domain_presence.{dim}"
                                if dim != "general"
                                else "current_period.paid.balance"
                            ],
                        }
                        for dim in dimensions
                    ],
                },
                ensure_ascii=False,
            ),
            prompt_tokens=100,
            completion_tokens=80,
            total_tokens=180,
            model="gpt-4o",
            latency_ms=50,
        )


class TestMonthlyRecapBatch:
    def test_generates_recap_for_user_with_activity(self, app) -> None:
        with app.app_context():
            user_id = _create_user()
            _seed_daily_insight(user_id, period=date(2026, 4, 15))

            generated = generate_monthly_recaps_for_all(
                reference_date=date(2026, 5, 1),
                llm_provider=_RecapProvider(),
            )

            assert generated == 1
            recap = AIInsight.query.filter_by(
                user_id=user_id,
                insight_type=InsightType.monthly,
                period_label="2026-04",
            ).first()
            assert recap is not None

    def test_idempotent_skips_existing_recap(self, app) -> None:
        with app.app_context():
            user_id = _create_user()
            _seed_daily_insight(user_id, period=date(2026, 4, 15))
            _seed_monthly_recap(user_id, period_label="2026-04")

            generated = generate_monthly_recaps_for_all(
                reference_date=date(2026, 5, 1),
                llm_provider=_RecapProvider(),
            )

            assert generated == 0

    def test_skips_users_without_activity_in_target_month(self, app) -> None:
        with app.app_context():
            user_id = _create_user()
            # Activity in March, not April → April batch must skip the user.
            _seed_daily_insight(user_id, period=date(2026, 3, 10))

            generated = generate_monthly_recaps_for_all(
                reference_date=date(2026, 5, 1),
                llm_provider=_RecapProvider(),
            )

            assert generated == 0
