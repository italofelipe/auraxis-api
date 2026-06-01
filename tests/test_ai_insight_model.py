"""Tests for AIInsight model and migration (#1227)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from app.models.ai_insight import AIInsight, InsightType


class TestAIInsightModel:
    def test_create_daily_insight(self, app) -> None:
        with app.app_context():
            from app.extensions.database import db

            user_id = uuid.uuid4()
            today = date.today()

            insight = AIInsight(
                user_id=user_id,
                content="Você gastou 30% a mais em alimentação este mês.",
                insight_type=InsightType.daily,
                period_label=today.strftime("%Y-%m-%d"),
                period_start=today,
                period_end=today,
                model="gpt-4o-mini",
                tokens_used=320,
                cost_usd=0.000048,
            )
            db.session.add(insight)
            db.session.commit()

            fetched = db.session.get(AIInsight, insight.id)
            assert fetched is not None
            assert fetched.insight_type == InsightType.daily
            assert fetched.period_label == today.strftime("%Y-%m-%d")
            assert fetched.content == "Você gastou 30% a mais em alimentação este mês."
            assert fetched.previous_insight_id is None

    def test_insight_chain_via_previous_insight_id(self, app) -> None:
        with app.app_context():
            from app.extensions.database import db

            user_id = uuid.uuid4()
            today = date.today()
            # timedelta, não replace(day=today.day-1): no dia 1 do mês day-1=0 e
            # date.replace(day=0) levanta "day is out of range for month".
            yesterday = today - timedelta(days=1)

            first = AIInsight(
                user_id=user_id,
                content="Insight de ontem.",
                insight_type=InsightType.daily,
                period_label=yesterday.strftime("%Y-%m-%d"),
                period_start=today,
                period_end=today,
                model="gpt-4o-mini",
                tokens_used=100,
                cost_usd=0.000015,
            )
            db.session.add(first)
            db.session.flush()

            second = AIInsight(
                user_id=user_id,
                content="Insight de hoje, referenciando ontem.",
                insight_type=InsightType.daily,
                period_label=today.strftime("%Y-%m-%d"),
                period_start=today,
                period_end=today,
                model="gpt-4o-mini",
                tokens_used=340,
                cost_usd=0.000051,
                previous_insight_id=first.id,
            )
            db.session.add(second)
            db.session.commit()

            fetched = db.session.get(AIInsight, second.id)
            assert fetched.previous_insight_id == first.id

    def test_all_insight_types_are_valid(self, app) -> None:
        with app.app_context():
            from app.extensions.database import db

            for itype in InsightType:
                user_id = uuid.uuid4()
                insight = AIInsight(
                    user_id=user_id,
                    content=f"Insight de tipo {itype.value}",
                    insight_type=itype,
                    period_label="2026-05",
                    period_start=date(2026, 5, 1),
                    period_end=date(2026, 5, 31),
                    model="gpt-4o-mini",
                    tokens_used=100,
                    cost_usd=0.00001,
                )
                db.session.add(insight)
            db.session.commit()
            count = db.session.query(AIInsight).count()
            assert count >= len(list(InsightType))

    def test_created_at_is_set_automatically(self, app) -> None:
        with app.app_context():
            from app.extensions.database import db

            insight = AIInsight(
                user_id=uuid.uuid4(),
                content="Auto timestamp test.",
                insight_type=InsightType.weekly,
                period_label="2026-W20",
                period_start=date(2026, 5, 11),
                period_end=date(2026, 5, 17),
                model="gpt-4o-mini",
                tokens_used=200,
                cost_usd=0.00003,
            )
            db.session.add(insight)
            db.session.commit()
            assert insight.created_at is not None

    def test_query_by_user_and_period_label(self, app) -> None:
        with app.app_context():
            from app.extensions.database import db

            user_id = uuid.uuid4()
            today_label = date.today().strftime("%Y-%m-%d")

            insight = AIInsight(
                user_id=user_id,
                content="Query test.",
                insight_type=InsightType.daily,
                period_label=today_label,
                period_start=date.today(),
                period_end=date.today(),
                model="gpt-4o-mini",
                tokens_used=150,
                cost_usd=0.00002,
            )
            db.session.add(insight)
            db.session.commit()

            result = (
                db.session.query(AIInsight)
                .filter_by(
                    user_id=user_id,
                    period_label=today_label,
                    insight_type=InsightType.daily,
                )
                .first()
            )
            assert result is not None
            assert result.id == insight.id

    def test_repr_is_informative(self, app) -> None:
        with app.app_context():
            insight = AIInsight(
                user_id=uuid.uuid4(),
                content="Test repr.",
                insight_type=InsightType.daily,
                period_label="2026-05-11",
                period_start=date(2026, 5, 11),
                period_end=date(2026, 5, 11),
                model="gpt-4o-mini",
                tokens_used=100,
                cost_usd=0.00001,
            )
            r = repr(insight)
            assert "AIInsight" in r
            assert "daily" in r
