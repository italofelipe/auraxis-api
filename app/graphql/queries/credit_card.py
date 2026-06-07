"""GraphQL queries for the Credit Cards domain (MVP-3).

Provides `creditCards`, `creditCardBill(cardId, month)`, and
`creditCardUtilization(cardId)` — parity with the REST endpoints in
`app/controllers/credit_card/`.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import graphene

from app.graphql.auth import get_current_user_required
from app.graphql.observability import log_graphql_resolver
from app.graphql.scalars import DecimalScalar
from app.models.credit_card import CreditCard
from app.services.credit_card_bill_service import (
    BillCycle,
    BillSummary,
    Utilization,
    compute_bill,
    compute_utilization,
)


class CreditCardType(graphene.ObjectType):
    id = graphene.String(required=True)
    name = graphene.String(required=True)
    brand = graphene.String()
    limit_amount = DecimalScalar()
    closing_day = graphene.Int()
    due_day = graphene.Int()
    bank = graphene.String()
    description = graphene.String()
    benefits = graphene.List(graphene.String)
    created_at = graphene.String()
    updated_at = graphene.String()


class CreditCardListType(graphene.ObjectType):
    credit_cards = graphene.List(CreditCardType)
    total = graphene.Int()


class BillCycleType(graphene.ObjectType):
    start_date = graphene.String(required=True)
    end_date = graphene.String(required=True)
    due_date = graphene.String(required=True)
    status = graphene.String(required=True)


class BillTransactionType(graphene.ObjectType):
    id = graphene.String(required=True)
    title = graphene.String(required=True)
    amount = DecimalScalar(required=True)
    due_date = graphene.String()
    status = graphene.String()
    type = graphene.String()


class CreditCardBillType(graphene.ObjectType):
    cycle = graphene.Field(BillCycleType, required=True)
    transactions = graphene.List(BillTransactionType)
    total_amount = DecimalScalar(required=True)
    paid_amount = DecimalScalar(required=True)
    pending_amount = DecimalScalar(required=True)


class CreditCardUtilizationType(graphene.ObjectType):
    cycle = graphene.Field(BillCycleType, required=True)
    committed_amount = DecimalScalar(required=True)
    available_amount = DecimalScalar()
    limit_amount = DecimalScalar()
    utilization_pct = graphene.Float()


def _to_card_type(c: CreditCard) -> CreditCardType:
    return CreditCardType(
        id=str(c.id),
        name=c.name,
        brand=c.brand,
        limit_amount=c.limit_amount,
        closing_day=c.closing_day,
        due_day=c.due_day,
        bank=c.bank,
        description=c.description,
        benefits=c.benefits_list,
        created_at=c.created_at.isoformat() if c.created_at else None,
        updated_at=c.updated_at.isoformat() if c.updated_at else None,
    )


def _to_cycle_type(cycle: BillCycle) -> BillCycleType:
    return BillCycleType(
        start_date=cycle.start_date.isoformat(),
        end_date=cycle.end_date.isoformat(),
        due_date=cycle.due_date.isoformat(),
        status=cycle.status,
    )


def _to_bill_type(bill: BillSummary) -> CreditCardBillType:
    transactions = [
        BillTransactionType(
            id=str(tx.id),
            title=tx.title,
            amount=tx.amount,
            due_date=tx.due_date.isoformat() if tx.due_date else None,
            status=tx.status.value if hasattr(tx.status, "value") else str(tx.status),
            type=tx.type.value if hasattr(tx.type, "value") else str(tx.type),
        )
        for tx in bill.transactions
    ]
    return CreditCardBillType(
        cycle=_to_cycle_type(bill.cycle),
        transactions=transactions,
        total_amount=bill.total_amount,
        paid_amount=bill.paid_amount,
        pending_amount=bill.pending_amount,
    )


def _to_utilization_type(u: Utilization) -> CreditCardUtilizationType:
    return CreditCardUtilizationType(
        cycle=_to_cycle_type(u.cycle),
        committed_amount=u.committed_amount,
        available_amount=u.available_amount,
        limit_amount=u.limit_amount,
        utilization_pct=u.utilization_pct,
    )


class CreditCardQueryMixin:
    credit_cards = graphene.Field(CreditCardListType)
    credit_card_bill = graphene.Field(
        CreditCardBillType,
        card_id=graphene.UUID(required=True),
        month=graphene.String(required=True),
    )
    credit_card_utilization = graphene.Field(
        CreditCardUtilizationType,
        card_id=graphene.UUID(required=True),
    )

    @log_graphql_resolver("creditCards")
    def resolve_credit_cards(self, _info: graphene.ResolveInfo) -> CreditCardListType:
        user = get_current_user_required()
        rows = (
            CreditCard.query.filter_by(user_id=user.id).order_by(CreditCard.name).all()
        )
        return CreditCardListType(
            credit_cards=[_to_card_type(c) for c in rows], total=len(rows)
        )

    @log_graphql_resolver("creditCardBill")
    def resolve_credit_card_bill(
        self,
        _info: graphene.ResolveInfo,
        card_id: Any,
        month: str,
    ) -> CreditCardBillType | None:
        user = get_current_user_required()
        card: CreditCard | None = CreditCard.query.filter_by(
            id=card_id, user_id=user.id
        ).first()
        if card is None:
            return None
        if card.closing_day is None or card.due_day is None:
            return None
        try:
            bill = compute_bill(card, month=month, today=date.today())
        except ValueError:
            return None
        return _to_bill_type(bill)

    @log_graphql_resolver("creditCardUtilization")
    def resolve_credit_card_utilization(
        self,
        _info: graphene.ResolveInfo,
        card_id: Any,
    ) -> CreditCardUtilizationType | None:
        user = get_current_user_required()
        card: CreditCard | None = CreditCard.query.filter_by(
            id=card_id, user_id=user.id
        ).first()
        if card is None:
            return None
        if card.closing_day is None or card.due_day is None:
            return None
        u = compute_utilization(card, today=date.today())
        return _to_utilization_type(u)
