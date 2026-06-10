from __future__ import annotations

import json
import sys
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from app.extensions.database import db
from app.models.ai_insight import AIInsight, InsightType
from app.models.ai_insight_run import AIInsightRun, AIInsightRunStatus
from app.models.user import User
from app.services.ai_monthly_report_service import (
    create_monthly_report_run,
    enqueue_monthly_report_run,
    get_ai_insight_by_id,
    get_monthly_report_run_status,
    process_monthly_report_run,
)
from app.services.email_provider import get_email_outbox
from app.services.llm_provider import LLMResponse


def _create_user() -> uuid.UUID:
    user = User(
        name="Mensal Tester",
        email=f"monthly-{uuid.uuid4().hex[:8]}@email.com",
        password="hash",
    )
    db.session.add(user)
    db.session.commit()
    return user.id


def _register_and_login(client, prefix: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    email = f"{prefix}-{suffix}@test.com"
    reg = client.post(
        "/auth/register",
        json={
            "name": f"{prefix}-{suffix}",
            "email": email,
            "password": "StrongPass@123",
        },
    )
    assert reg.status_code == 201
    login = client.post(
        "/auth/login",
        json={"email": email, "password": "StrongPass@123"},
    )
    assert login.status_code == 200
    return login.get_json()["token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-API-Contract": "v2"}


def _grant_premium(app, token: str) -> uuid.UUID:
    with app.app_context():
        from flask_jwt_extended import decode_token

        from app.models.entitlement import Entitlement, EntitlementSource

        user_id = uuid.UUID(decode_token(token)["sub"])
        db.session.add(
            Entitlement(
                user_id=user_id,
                feature_key="advanced_simulations",
                source=EntitlementSource.MANUAL,
                expires_at=None,
            )
        )
        db.session.commit()
        return user_id


def _insight_content(summary: str, dimension: str = "general") -> str:
    return json.dumps(
        {
            "summary": summary,
            "items": [
                {
                    "type": "saude_financeira",
                    "dimension": dimension,
                    "title": "Resumo",
                    "message": summary,
                    "evidence": ["current_period.paid.balance"],
                }
            ],
        },
        ensure_ascii=False,
    )


def _create_insight(
    user_id: uuid.UUID,
    *,
    insight_type: InsightType,
    period_label: str,
    period_start: date,
    period_end: date,
    summary: str,
) -> AIInsight:
    insight = AIInsight(
        user_id=user_id,
        content=_insight_content(summary),
        insight_type=insight_type,
        period_label=period_label,
        period_start=period_start,
        period_end=period_end,
        model="gpt-test",
        tokens_used=100,
        cost_usd=Decimal("0.00001"),
    )
    db.session.add(insight)
    db.session.commit()
    return insight


def _monthly_llm_response() -> LLMResponse:
    dimensions = [
        ("general", "Panorama mensal", "monthly_report_context.daily_insights"),
        (
            "transactions",
            "Movimentação mensal",
            "data_quality.domain_presence.transactions",
        ),
        ("goals", "Metas do mês", "data_quality.domain_presence.goals"),
        ("budgets", "Orçamentos do mês", "data_quality.domain_presence.budgets"),
        ("credit_cards", "Cartões do mês", "data_quality.domain_presence.credit_cards"),
        ("wallet", "Carteira do mês", "data_quality.domain_presence.wallet"),
    ]
    return LLMResponse(
        content=json.dumps(
            {
                "summary": "Relatório mensal consolidado.",
                "items": [
                    {
                        "type": "saude_financeira",
                        "dimension": dimension,
                        "title": title,
                        "message": (
                            "O mês foi consolidado com base nos insights diários."
                        ),
                        "evidence": [evidence],
                    }
                    for dimension, title, evidence in dimensions
                ],
            },
            ensure_ascii=False,
        ),
        prompt_tokens=100,
        completion_tokens=80,
        total_tokens=180,
        model="gpt-test",
        latency_ms=50,
    )


class StaticProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate_with_usage(
        self, prompt: str, response_schema=None, max_tokens=None
    ) -> LLMResponse:
        self.calls += 1
        assert "monthly_report_context" in prompt
        assert "Daily 1" in prompt
        assert "Relatório anterior" in prompt
        return _monthly_llm_response()


class FailingProvider:
    def generate_with_usage(
        self, prompt: str, response_schema=None, max_tokens=None
    ) -> LLMResponse:
        raise RuntimeError("provider unavailable")


class TestMonthlyReportService:
    def test_create_run_persists_monthly_context_with_daily_history(self, app) -> None:
        with app.app_context():
            user_id = _create_user()
            previous = _create_insight(
                user_id,
                insight_type=InsightType.monthly,
                period_label="2026-04",
                period_start=date(2026, 4, 1),
                period_end=date(2026, 4, 30),
                summary="Relatório anterior",
            )
            _create_insight(
                user_id,
                insight_type=InsightType.daily,
                period_label="2026-05-01",
                period_start=date(2026, 5, 1),
                period_end=date(2026, 5, 1),
                summary="Daily 1",
            )
            _create_insight(
                user_id,
                insight_type=InsightType.daily,
                period_label="2026-05-02",
                period_start=date(2026, 5, 2),
                period_end=date(2026, 5, 2),
                summary="Daily 2",
            )

            result = create_monthly_report_run(
                user_id=user_id,
                anchor_date=date(2026, 5, 21),
            )

            run = db.session.get(AIInsightRun, uuid.UUID(result["run_id"]))
            assert run is not None
            assert run.status == AIInsightRunStatus.previewed
            assert run.period_type == InsightType.monthly
            assert run.period_label == "2026-05"
            context = run.snapshot_json["monthly_report_context"]
            assert [item["period_label"] for item in context["daily_insights"]] == [
                "2026-05-01",
                "2026-05-02",
            ]
            assert context["previous_monthly_insight"]["period_label"] == (
                previous.period_label
            )
            assert context["previous_monthly_insight"]["summary"] == (
                "Relatório anterior"
            )

    def test_process_run_generates_insight_and_emails_deep_link(self, app) -> None:
        with app.app_context():
            user_id = _create_user()
            _create_insight(
                user_id,
                insight_type=InsightType.daily,
                period_label="2026-05-01",
                period_start=date(2026, 5, 1),
                period_end=date(2026, 5, 1),
                summary="Daily 1",
            )
            _create_insight(
                user_id,
                insight_type=InsightType.monthly,
                period_label="2026-04",
                period_start=date(2026, 4, 1),
                period_end=date(2026, 4, 30),
                summary="Relatório anterior",
            )
            run_result = create_monthly_report_run(
                user_id=user_id,
                anchor_date=date(2026, 5, 21),
            )
            provider = StaticProvider()

            result = process_monthly_report_run(
                run_id=uuid.UUID(run_result["run_id"]),
                llm_provider=provider,
            )

            run = db.session.get(AIInsightRun, uuid.UUID(run_result["run_id"]))
            assert run is not None
            assert run.status == AIInsightRunStatus.generated
            assert run.ai_insight_id is not None
            assert result["status"] == "generated"
            assert result["insight_id"] == str(run.ai_insight_id)
            assert result["deep_link"].endswith(f"/insights?open={run.ai_insight_id}")
            assert provider.calls == 1

            outbox = get_email_outbox()
            assert outbox[-1]["tag"] == "monthly_ai_insight_ready"
            assert str(run.ai_insight_id) in outbox[-1]["html"]
            assert str(run.ai_insight_id) in outbox[-1]["text"]

            try:
                process_monthly_report_run(run_id=uuid.uuid4())
            except ValueError as exc:
                assert "run_id inválido" in str(exc)
            else:  # pragma: no cover - defensive assertion
                raise AssertionError("expected missing run to be rejected")

    def test_month_bounds_supports_december_and_invalid_user(self, app) -> None:
        with app.app_context():
            user_id = _create_user()

            result = create_monthly_report_run(
                user_id=user_id,
                anchor_date=date(2026, 12, 21),
            )

            assert result["period_start"] == "2026-12-01"
            assert result["period_end"] == "2026-12-31"

            missing_user_id = uuid.uuid4()
            try:
                create_monthly_report_run(user_id=missing_user_id)
            except ValueError as exc:
                assert "user_id" in str(exc)
            else:  # pragma: no cover - defensive assertion
                raise AssertionError("expected missing user to be rejected")

    def test_process_run_is_idempotent_for_generated_status(self, app) -> None:
        with app.app_context():
            user_id = _create_user()
            run_result = create_monthly_report_run(
                user_id=user_id,
                anchor_date=date(2026, 5, 21),
            )
            run = db.session.get(AIInsightRun, uuid.UUID(run_result["run_id"]))
            assert run is not None
            run.status = AIInsightRunStatus.generated
            run.ai_insight_id = uuid.uuid4()
            db.session.commit()

            result = process_monthly_report_run(
                run_id=run.id,
                llm_provider=StaticProvider(),
            )

            assert result["status"] == "generated"
            assert result["insight_id"] == str(run.ai_insight_id)

    def test_process_run_rejects_invalid_status_and_marks_failures(self, app) -> None:
        with app.app_context():
            user_id = _create_user()
            run_result = create_monthly_report_run(
                user_id=user_id,
                anchor_date=date(2026, 5, 21),
            )
            run = db.session.get(AIInsightRun, uuid.UUID(run_result["run_id"]))
            assert run is not None
            run.status = AIInsightRunStatus.rejected
            db.session.commit()

            try:
                process_monthly_report_run(run_id=run.id, llm_provider=StaticProvider())
            except ValueError as exc:
                assert "disponível" in str(exc)
            else:  # pragma: no cover - defensive assertion
                raise AssertionError("expected rejected run to fail")

            run.status = AIInsightRunStatus.previewed
            db.session.commit()

            try:
                process_monthly_report_run(
                    run_id=run.id,
                    llm_provider=FailingProvider(),
                )
            except RuntimeError as exc:
                assert "provider unavailable" in str(exc)
            else:  # pragma: no cover - defensive assertion
                raise AssertionError("expected provider failure to bubble up")

            db.session.refresh(run)
            assert run.status == AIInsightRunStatus.failed
            assert run.rejection_reasons_json == ["provider unavailable"]

    def test_enqueue_monthly_report_run_uses_sync_fallback_without_redis(
        self, app, monkeypatch
    ) -> None:
        with app.app_context():
            monkeypatch.delenv("REDIS_URL", raising=False)
            with patch(
                "app.services.ai_monthly_report_service.process_monthly_report_run",
                return_value={"run_id": "run-1", "status": "generated"},
            ) as process_run:
                result = enqueue_monthly_report_run(run_id=uuid.uuid4())

            assert result == {"run_id": "run-1", "status": "generated"}
            process_run.assert_called_once()

    def test_enqueue_monthly_report_run_creates_rq_job(self, app, monkeypatch) -> None:
        with app.app_context():
            user_id = _create_user()
            run_result = create_monthly_report_run(
                user_id=user_id,
                anchor_date=date(2026, 5, 21),
            )
            run_id = uuid.UUID(run_result["run_id"])
            queued_calls: list[dict[str, object]] = []

            class FakeQueue:
                def __init__(self, name: str, connection: object) -> None:
                    queued_calls.append({"name": name, "connection": connection})

                def enqueue(
                    self,
                    job_path: str,
                    run_id_arg: str,
                    *,
                    job_timeout: str,
                ) -> SimpleNamespace:
                    queued_calls.append(
                        {
                            "job_path": job_path,
                            "run_id": run_id_arg,
                            "job_timeout": job_timeout,
                        }
                    )
                    return SimpleNamespace(id="job-123")

            redis_connection = object()
            monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
            monkeypatch.setitem(
                sys.modules,
                "redis",
                SimpleNamespace(
                    Redis=SimpleNamespace(from_url=lambda url: redis_connection),
                ),
            )
            monkeypatch.setitem(sys.modules, "rq", SimpleNamespace(Queue=FakeQueue))

            result = enqueue_monthly_report_run(run_id=run_id)

            assert result["queued"] is True
            assert result["job_id"] == "job-123"
            assert result["run_id"] == str(run_id)
            assert queued_calls[0]["connection"] is redis_connection
            assert queued_calls[1]["job_path"] == (
                "app.jobs.ai_insight_jobs.generate_monthly_report"
            )
            assert queued_calls[1]["job_timeout"] == "20m"

    def test_enqueue_monthly_report_run_falls_back_when_rq_fails(
        self, app, monkeypatch
    ) -> None:
        class BrokenQueue:
            def __init__(self, name: str, connection: object) -> None:
                raise RuntimeError("redis down")

        with app.app_context():
            monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
            monkeypatch.setitem(
                sys.modules,
                "redis",
                SimpleNamespace(Redis=SimpleNamespace(from_url=lambda url: object())),
            )
            monkeypatch.setitem(sys.modules, "rq", SimpleNamespace(Queue=BrokenQueue))
            with patch(
                "app.services.ai_monthly_report_service.process_monthly_report_run",
                return_value={"run_id": "fallback", "status": "generated"},
            ) as process_run:
                result = enqueue_monthly_report_run(run_id=uuid.uuid4())

            assert result["run_id"] == "fallback"
            process_run.assert_called_once()

    def test_lookup_helpers_reject_foreign_or_missing_records(self, app) -> None:
        with app.app_context():
            user_id = _create_user()
            other_user_id = _create_user()
            run_result = create_monthly_report_run(
                user_id=user_id,
                anchor_date=date(2026, 5, 21),
            )
            insight = _create_insight(
                user_id,
                insight_type=InsightType.monthly,
                period_label="2026-05",
                period_start=date(2026, 5, 1),
                period_end=date(2026, 5, 31),
                summary="Relatório mensal consolidado",
            )

            assert (
                get_monthly_report_run_status(
                    user_id=user_id,
                    run_id=uuid.UUID(run_result["run_id"]),
                )["run_id"]
                == run_result["run_id"]
            )
            assert (
                get_ai_insight_by_id(user_id=user_id, insight_id=insight.id)["summary"]
                == "Relatório mensal consolidado"
            )

            for callback in (
                lambda: get_monthly_report_run_status(
                    user_id=other_user_id,
                    run_id=uuid.UUID(run_result["run_id"]),
                ),
                lambda: get_ai_insight_by_id(
                    user_id=other_user_id,
                    insight_id=insight.id,
                ),
            ):
                try:
                    callback()
                except ValueError as exc:
                    assert "não encontrado" in str(exc)
                else:  # pragma: no cover - defensive assertion
                    raise AssertionError("expected ownership guard to fail")


class TestMonthlyReportEndpoints:
    def test_monthly_report_endpoint_enqueues_traceable_run(self, app, client) -> None:
        token = _register_and_login(client, "monthly-endpoint")
        _grant_premium(app, token)
        run_id = uuid.uuid4()

        with (
            patch(
                "app.controllers.ai.resources.ensure_ai_consent_granted",
                return_value="v1.0",
            ),
            patch(
                "app.controllers.ai.resources.create_monthly_report_run",
                return_value={"run_id": str(run_id), "status": "previewed"},
            ) as create_run,
            patch(
                "app.controllers.ai.resources.enqueue_monthly_report_run",
                return_value={
                    "run_id": str(run_id),
                    "status": "previewed",
                    "queued": True,
                    "job_id": "job-1",
                },
            ) as enqueue_run,
        ):
            resp = client.post(
                "/ai/insights/monthly-report",
                headers=_auth(token),
                json={"anchor_date": "2026-05-21"},
            )

        assert resp.status_code == 202
        payload = resp.get_json()["data"]
        assert payload["run_id"] == str(run_id)
        assert payload["queued"] is True
        create_run.assert_called_once()
        enqueue_run.assert_called_once_with(run_id=run_id)

    def test_monthly_report_endpoint_can_generate_synchronously(
        self, app, client
    ) -> None:
        token = _register_and_login(client, "monthly-sync")
        _grant_premium(app, token)
        run_id = uuid.uuid4()

        with (
            patch(
                "app.controllers.ai.resources.ensure_ai_consent_granted",
                return_value="v1.0",
            ),
            patch(
                "app.controllers.ai.resources.create_monthly_report_run",
                return_value={"run_id": str(run_id), "status": "previewed"},
            ),
            patch(
                "app.controllers.ai.resources.process_monthly_report_run",
                return_value={
                    "run_id": str(run_id),
                    "status": "generated",
                    "insight_id": str(uuid.uuid4()),
                },
            ) as process_run,
        ):
            resp = client.post(
                "/ai/insights/monthly-report",
                headers=_auth(token),
                json={"anchor_date": "2026-05-21", "enqueue": False},
            )

        assert resp.status_code == 200
        assert resp.get_json()["message"] == "Relatório mensal gerado com sucesso"
        process_run.assert_called_once_with(run_id=run_id)

    def test_monthly_report_endpoint_rejects_invalid_anchor_date(
        self, app, client
    ) -> None:
        token = _register_and_login(client, "monthly-invalid-date")
        _grant_premium(app, token)

        resp = client.post(
            "/ai/insights/monthly-report",
            headers=_auth(token),
            json={"anchor_date": "21/05/2026"},
        )

        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "VALIDATION_ERROR"

    def test_monthly_report_endpoint_requires_premium(self, client) -> None:
        token = _register_and_login(client, "monthly-free")

        with patch("app.controllers.ai.resources.has_entitlement", return_value=False):
            resp = client.post(
                "/ai/insights/monthly-report",
                headers=_auth(token),
                json={"anchor_date": "2026-05-21"},
            )

        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == "ENTITLEMENT_REQUIRED"

    def test_monthly_report_endpoint_maps_consent_required(self, app, client) -> None:
        token = _register_and_login(client, "monthly-no-consent")
        _grant_premium(app, token)

        from app.services.ai_lgpd import AIConsentRequiredError

        with patch(
            "app.controllers.ai.resources.ensure_ai_consent_granted",
            side_effect=AIConsentRequiredError(),
        ):
            resp = client.post(
                "/ai/insights/monthly-report",
                headers=_auth(token),
                json={"anchor_date": "2026-05-21"},
            )

        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == "AI_CONSENT_REQUIRED"

    def test_monthly_report_endpoint_maps_budget_and_provider_errors(
        self, app, client
    ) -> None:
        from app.services.ai_advisory_service import AIInsightCostBudgetExceededError
        from app.services.llm_provider import LLMProviderError

        token = _register_and_login(client, "monthly-errors")
        _grant_premium(app, token)
        run_id = uuid.uuid4()

        cases = [
            (
                AIInsightCostBudgetExceededError(
                    "monthly budget exceeded",
                    scope="monthly",
                    limit_usd=Decimal("1.00"),
                    spent_usd=Decimal("1.01"),
                ),
                429,
                "AI_INSIGHT_BUDGET_EXCEEDED",
            ),
            (LLMProviderError("provider offline"), 500, "INTERNAL_ERROR"),
            (RuntimeError("unexpected"), 500, "INTERNAL_ERROR"),
        ]

        for side_effect, status_code, error_code in cases:
            with (
                patch(
                    "app.controllers.ai.resources.ensure_ai_consent_granted",
                    return_value="v1.0",
                ),
                patch(
                    "app.controllers.ai.resources.create_monthly_report_run",
                    return_value={"run_id": str(run_id), "status": "previewed"},
                ),
                patch(
                    "app.controllers.ai.resources.enqueue_monthly_report_run",
                    side_effect=side_effect,
                ),
            ):
                resp = client.post(
                    "/ai/insights/monthly-report",
                    headers=_auth(token),
                    json={"anchor_date": "2026-05-21"},
                )

            assert resp.status_code == status_code
            assert resp.get_json()["error"]["code"] == error_code

    def test_insight_detail_endpoint_returns_single_owned_insight(
        self, app, client
    ) -> None:
        token = _register_and_login(client, "monthly-detail")

        with app.app_context():
            from flask_jwt_extended import decode_token

            user_id = uuid.UUID(decode_token(token)["sub"])
            insight = _create_insight(
                user_id,
                insight_type=InsightType.monthly,
                period_label="2026-05",
                period_start=date(2026, 5, 1),
                period_end=date(2026, 5, 31),
                summary="Relatório mensal consolidado",
            )
            insight_id = insight.id

        resp = client.get(f"/ai/insights/{insight_id}", headers=_auth(token))

        assert resp.status_code == 200
        payload = resp.get_json()["data"]
        assert payload["id"] == str(insight_id)
        assert payload["period_type"] == "monthly"
        assert payload["summary"] == "Relatório mensal consolidado"

    def test_run_status_endpoint_handles_invalid_and_missing_ids(
        self, app, client
    ) -> None:
        token = _register_and_login(client, "monthly-run-errors")

        invalid = client.get("/ai/insights/runs/not-a-uuid", headers=_auth(token))
        missing = client.get(f"/ai/insights/runs/{uuid.uuid4()}", headers=_auth(token))

        assert invalid.status_code == 400
        assert missing.status_code == 404

    def test_run_status_endpoint_returns_owned_run(self, app, client) -> None:
        token = _register_and_login(client, "monthly-run-status")

        with app.app_context():
            from flask_jwt_extended import decode_token

            user_id = uuid.UUID(decode_token(token)["sub"])
            result = create_monthly_report_run(
                user_id=user_id,
                anchor_date=date(2026, 5, 21),
            )
            run_id = result["run_id"]

        resp = client.get(f"/ai/insights/runs/{run_id}", headers=_auth(token))

        assert resp.status_code == 200
        payload = resp.get_json()["data"]
        assert payload["run_id"] == run_id
        assert payload["status"] == "previewed"

    def test_insight_detail_endpoint_handles_invalid_and_missing_ids(
        self, app, client
    ) -> None:
        token = _register_and_login(client, "monthly-detail-errors")

        invalid = client.get("/ai/insights/not-a-uuid", headers=_auth(token))
        missing = client.get(f"/ai/insights/{uuid.uuid4()}", headers=_auth(token))

        assert invalid.status_code == 400
        assert missing.status_code == 404


class TestMonthlyReportJob:
    def test_generate_monthly_report_uses_existing_app_context(self, app) -> None:
        from app.jobs.ai_insight_jobs import generate_monthly_report

        with app.app_context():
            run_id = uuid.uuid4()
            with patch(
                "app.services.ai_monthly_report_service.process_monthly_report_run",
                return_value={"run_id": str(run_id)},
            ) as process_run:
                result = generate_monthly_report(str(run_id))

        assert result == {"run_id": str(run_id)}
        process_run.assert_called_once_with(run_id=run_id)

    def test_generate_monthly_report_creates_context_when_needed(self) -> None:
        from app.jobs.ai_insight_jobs import generate_monthly_report

        entered: list[str] = []

        class FakeApp:
            def app_context(self):
                class Context:
                    def __enter__(self):
                        entered.append("enter")
                        return self

                    def __exit__(self, exc_type, exc, tb):
                        entered.append("exit")
                        return False

                return Context()

        run_id = uuid.uuid4()
        with (
            patch("app.jobs.ai_insight_jobs.has_app_context", return_value=False),
            patch("app.create_app", return_value=FakeApp()) as create_app,
            patch(
                "app.services.ai_monthly_report_service.process_monthly_report_run",
                return_value={"run_id": str(run_id)},
            ) as process_run,
        ):
            result = generate_monthly_report(str(run_id))

        assert result == {"run_id": str(run_id)}
        assert entered == ["enter", "exit"]
        create_app.assert_called_once()
        process_run.assert_called_once_with(run_id=run_id)
