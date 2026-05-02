from __future__ import annotations

from uuid import UUID

import graphene

from app.application.services.wallet_application_service import (
    WalletApplicationError,
    WalletApplicationService,
)
from app.graphql.auth import get_current_user_required
from app.graphql.queries.common import paginate
from app.graphql.schema_utils import _validate_pagination_values
from app.graphql.types import (
    PaginationType,
    TickerListPayloadType,
    TickerType,
    WalletHistoryPayloadType,
    WalletListPayloadType,
)
from app.graphql.wallet_presenters import (
    raise_wallet_graphql_error,
    to_wallet_history_item,
    to_wallet_type,
)
from app.models.user_ticker import UserTicker


class WalletQueryMixin:
    wallet_entries = graphene.Field(
        WalletListPayloadType,
        page=graphene.Int(default_value=1),
        per_page=graphene.Int(default_value=10),
    )
    wallet_history = graphene.Field(
        WalletHistoryPayloadType,
        investment_id=graphene.UUID(required=True),
        page=graphene.Int(default_value=1),
        per_page=graphene.Int(default_value=5),
    )
    tickers = graphene.Field(
        TickerListPayloadType,
        page=graphene.Int(default_value=1),
        per_page=graphene.Int(default_value=50),
    )

    def resolve_wallet_entries(
        self, _info: graphene.ResolveInfo, page: int, per_page: int
    ) -> WalletListPayloadType:
        _validate_pagination_values(page, per_page)
        user = get_current_user_required()
        service = WalletApplicationService.with_defaults(UUID(str(user.id)))
        try:
            result = service.list_entries(page=page, per_page=per_page)
        except WalletApplicationError as exc:
            raise_wallet_graphql_error(exc)

        items = [to_wallet_type(item) for item in result["items"]]
        pagination = result["pagination"]
        return WalletListPayloadType(
            items=items,
            pagination=paginate(
                total=pagination["total"],
                page=pagination["page"],
                per_page=pagination["per_page"],
            ),
        )

    def resolve_wallet_history(
        self,
        _info: graphene.ResolveInfo,
        investment_id: UUID,
        page: int,
        per_page: int,
    ) -> WalletHistoryPayloadType:
        _validate_pagination_values(page, per_page)
        user = get_current_user_required()
        service = WalletApplicationService.with_defaults(UUID(str(user.id)))
        try:
            result = service.get_history(
                investment_id,
                page=page,
                per_page=per_page,
            )
        except WalletApplicationError as exc:
            raise_wallet_graphql_error(exc)

        pagination = result["pagination"]
        mapped_items = [
            to_wallet_history_item(item)
            for item in result["items"]
            if isinstance(item, dict)
        ]
        return WalletHistoryPayloadType(
            items=mapped_items,
            pagination=PaginationType(
                total=pagination["total"],
                page=pagination["page"],
                per_page=pagination["per_page"],
                pages=pagination["pages"],
            ),
        )

    def resolve_tickers(
        self,
        _info: graphene.ResolveInfo,
        page: int = 1,
        per_page: int = 50,
    ) -> TickerListPayloadType:
        _validate_pagination_values(page, per_page)
        user = get_current_user_required()
        base_query = UserTicker.query.filter_by(user_id=user.id)
        total = base_query.count()
        offset = (page - 1) * per_page
        rows = (
            base_query.order_by(UserTicker.symbol.asc())
            .offset(offset)
            .limit(per_page)
            .all()
        )
        items = [
            TickerType(
                id=str(item.id),
                symbol=item.symbol,
                quantity=item.quantity,
                type=item.type,
            )
            for item in rows
        ]
        return TickerListPayloadType(
            items=items,
            pagination=paginate(total=total, page=page, per_page=per_page),
        )
