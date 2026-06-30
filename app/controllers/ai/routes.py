from __future__ import annotations

from .blueprint import ai_bp
from .resources import (
    AIChatAskAnythingResource,
    AIGoalProjectionResource,
    AIInsightChangeStatusResource,
    AIInsightDetailResource,
    AIInsightFeedbackResource,
    AIInsightGenerateResource,
    AIInsightHistoryResource,
    AIInsightRunStatusResource,
    AIMonthlyReportResource,
    AISpendingInsightsResource,
    AIWeeklySummaryResource,
)
from .spending_patterns_latest import AISpendingPatternsLatestResource
from .spending_patterns_proxy import AISpendingPatternsProxyResource

_ROUTES_REGISTERED = False


def register_ai_routes() -> None:
    global _ROUTES_REGISTERED
    if _ROUTES_REGISTERED:
        return

    ai_bp.add_url_rule(
        "/insights/generate",
        view_func=AIInsightGenerateResource.as_view("ai_insight_generate"),
        methods=["POST"],
    )
    ai_bp.add_url_rule(
        "/chat",
        view_func=AIChatAskAnythingResource.as_view("ai_chat_ask_anything"),
        methods=["POST"],
    )
    ai_bp.add_url_rule(
        "/insights/change-status",
        view_func=AIInsightChangeStatusResource.as_view("ai_insight_change_status"),
        methods=["GET"],
    )
    ai_bp.add_url_rule(
        "/insights/spending",
        view_func=AISpendingInsightsResource.as_view("ai_spending_insights"),
        methods=["GET"],
    )
    ai_bp.add_url_rule(
        "/insights/spending-patterns",
        view_func=AISpendingPatternsProxyResource.as_view("ai_spending_patterns"),
        methods=["POST"],
    )
    ai_bp.add_url_rule(
        "/insights/spending-patterns/latest",
        view_func=AISpendingPatternsLatestResource.as_view(
            "ai_spending_patterns_latest"
        ),
        methods=["GET"],
    )
    ai_bp.add_url_rule(
        "/goals/<goal_id>/projection",
        view_func=AIGoalProjectionResource.as_view("ai_goal_projection"),
        methods=["POST"],
    )
    ai_bp.add_url_rule(
        "/insights/weekly-summary",
        view_func=AIWeeklySummaryResource.as_view("ai_weekly_summary"),
        methods=["GET"],
    )
    ai_bp.add_url_rule(
        "/insights/monthly-report",
        view_func=AIMonthlyReportResource.as_view("ai_monthly_report"),
        methods=["POST"],
    )
    ai_bp.add_url_rule(
        "/insights/runs/<run_id>",
        view_func=AIInsightRunStatusResource.as_view("ai_insight_run_status"),
        methods=["GET"],
    )
    ai_bp.add_url_rule(
        "/insights/history",
        view_func=AIInsightHistoryResource.as_view("ai_insight_history"),
        methods=["GET"],
    )
    ai_bp.add_url_rule(
        "/insights/<insight_id>",
        view_func=AIInsightDetailResource.as_view("ai_insight_detail"),
        methods=["GET"],
    )
    ai_bp.add_url_rule(
        "/insights/<insight_id>/feedback",
        view_func=AIInsightFeedbackResource.as_view("ai_insight_feedback"),
        methods=["POST"],
    )
    _ROUTES_REGISTERED = True


register_ai_routes()
