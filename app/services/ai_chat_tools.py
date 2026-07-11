"""Read-only function-calling tools for the Ask-anything chat (#1548).

The chat's base context is a month-aware snapshot; these tools let the model
fetch what the snapshot cannot carry (other periods, targeted searches) instead
of answering "não tenho essa informação". Every tool is strictly read-only and
scoped to the authenticated user. Decision PO 2026-07-10; kill-switch via
``AI_CHAT_TOOLS_ENABLED``.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import or_

from app.models.transaction import Transaction, TransactionStatus, TransactionType

log = logging.getLogger(__name__)

_MAX_SEARCH_RESULTS = 20
_DEFAULT_SEARCH_WINDOW_DAYS = 365

CHAT_TOOLS_SPEC: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_transactions",
            "description": (
                "Busca transações do usuário por texto (título/descrição) e "
                "período. Use quando a pergunta citar um gasto/receita "
                "específico (ex.: 'salário', 'academia') ou um período fora "
                "do snapshot."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Texto a procurar no título/descrição.",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Início (YYYY-MM-DD). Default: 12 meses atrás.",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Fim (YYYY-MM-DD). Default: hoje.",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["income", "expense", "all"],
                        "description": "Filtrar por tipo. Default: all.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_period_summary",
            "description": (
                "Totais pagos e pendentes (receitas, despesas, saldo) de um "
                "período arbitrário."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "YYYY-MM-DD."},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD."},
                },
                "required": ["start_date", "end_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_wallet_valuation",
            "description": (
                "Valuation atual da carteira de investimentos (patrimônio, "
                "investido, lucro/prejuízo, por ativo)."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pending_overdue",
            "description": (
                "Compromissos não pagos: vencidos (com dias de atraso) e "
                "próximos vencimentos em 7/30 dias."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


def _money_str(value: Decimal | float | int | None) -> str:
    return f"{Decimal(str(value or 0)):.2f}"


def _parse_date(raw: Any, default: date) -> date:
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return default


def _serialize(tx: Transaction) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "date": tx.due_date.isoformat(),
        "title": str(tx.title or ""),
        "amount": _money_str(tx.amount),
        "type": tx.type.value if tx.type else None,
        "status": tx.status.value if tx.status else None,
    }
    tag = getattr(tx, "tag", None)
    if tag is not None and tag.name:
        payload["tag"] = str(tag.name)
    return payload


def _search_transactions(user_id: UUID, arguments: dict[str, Any]) -> dict[str, Any]:
    today = date.today()
    start = _parse_date(
        arguments.get("start_date"),
        today - timedelta(days=_DEFAULT_SEARCH_WINDOW_DAYS),
    )
    end = _parse_date(arguments.get("end_date"), today)
    query = Transaction.query.filter(
        Transaction.user_id == user_id,
        Transaction.deleted.is_(False),
        Transaction.status != TransactionStatus.CANCELLED,
        Transaction.due_date >= start,
        Transaction.due_date <= end,
    )
    text = str(arguments.get("query") or "").strip()
    if text:
        pattern = f"%{text}%"
        query = query.filter(
            or_(
                Transaction.title.ilike(pattern),
                Transaction.description.ilike(pattern),
            )
        )
    tx_type = str(arguments.get("type") or "all").lower()
    if tx_type == "income":
        query = query.filter(Transaction.type == TransactionType.INCOME)
    elif tx_type == "expense":
        query = query.filter(Transaction.type == TransactionType.EXPENSE)

    rows = cast(
        list[Transaction],
        query.order_by(Transaction.due_date.desc())
        .limit(_MAX_SEARCH_RESULTS + 1)
        .all(),
    )
    truncated = len(rows) > _MAX_SEARCH_RESULTS
    items = [_serialize(tx) for tx in rows[:_MAX_SEARCH_RESULTS]]
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "count": len(items),
        "truncated": truncated,
        "items": items,
    }


def _get_period_summary(user_id: UUID, arguments: dict[str, Any]) -> dict[str, Any]:
    today = date.today()
    start = _parse_date(arguments.get("start_date"), today.replace(day=1))
    end = _parse_date(arguments.get("end_date"), today)
    rows = cast(
        list[Transaction],
        Transaction.query.filter(
            Transaction.user_id == user_id,
            Transaction.deleted.is_(False),
            Transaction.status != TransactionStatus.CANCELLED,
            Transaction.due_date >= start,
            Transaction.due_date <= end,
        ).all(),
    )

    def _sum(txs: list[Transaction], tx_type: TransactionType) -> Decimal:
        return sum(
            (Decimal(str(tx.amount)) for tx in txs if tx.type == tx_type),
            Decimal("0"),
        )

    paid = [tx for tx in rows if tx.status == TransactionStatus.PAID]
    unpaid = [tx for tx in rows if tx.status != TransactionStatus.PAID]
    income = _sum(paid, TransactionType.INCOME)
    expense = _sum(paid, TransactionType.EXPENSE)
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "paid": {
            "income_total": _money_str(income),
            "expense_total": _money_str(expense),
            "balance": _money_str(income - expense),
        },
        "pending": {
            "income_total": _money_str(_sum(unpaid, TransactionType.INCOME)),
            "expense_total": _money_str(_sum(unpaid, TransactionType.EXPENSE)),
        },
        "transaction_count": len(rows),
    }


def _get_wallet_valuation(user_id: UUID, _: dict[str, Any]) -> dict[str, Any]:
    from app.services.portfolio_valuation_service import PortfolioValuationService

    valuation = PortfolioValuationService(user_id).get_portfolio_current_valuation()
    items = [
        {
            "name": item["name"],
            "asset_class": item["asset_class"],
            "ticker": item["ticker"],
            "current_value": item["current_value"],
            "invested_amount": item["invested_amount"],
            "profit_loss_amount": item["profit_loss_amount"],
            "profit_loss_percent": item["profit_loss_percent"],
            "valuation_source": item["valuation_source"],
        }
        for item in valuation["items"]
    ]
    return {"summary": valuation["summary"], "items": items}


def _get_pending_overdue(user_id: UUID, _: dict[str, Any]) -> dict[str, Any]:
    from app.services.financial_insight_context_builder import (
        FinancialInsightContextBuilder,
    )

    return FinancialInsightContextBuilder()._pending_commitments_payload(  # noqa: SLF001
        user_id=user_id,
        anchor=date.today(),
    )


_EXECUTORS = {
    "search_transactions": _search_transactions,
    "get_period_summary": _get_period_summary,
    "get_wallet_valuation": _get_wallet_valuation,
    "get_pending_overdue": _get_pending_overdue,
}


def execute_chat_tool(
    *,
    user_id: UUID,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Execute a read-only chat tool for *user_id*; errors become payloads.

    Tool failures must never abort the chat turn — the model receives an
    ``error`` field and can degrade gracefully.
    """
    executor = _EXECUTORS.get(name)
    if executor is None:
        return {"error": f"unknown_tool: {name}"}
    try:
        return executor(user_id, arguments or {})
    except Exception as exc:  # defensive: tools must not break the chat
        log.warning("ai_chat.tool_failed user=%s tool=%s error=%s", user_id, name, exc)
        return {"error": "tool_execution_failed"}


__all__ = ["CHAT_TOOLS_SPEC", "execute_chat_tool"]
