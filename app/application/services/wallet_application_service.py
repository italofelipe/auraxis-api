from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Callable, cast
from uuid import UUID

from marshmallow import ValidationError

from app.extensions.database import db
from app.models.wallet import Wallet
from app.schemas.wallet_schema import WalletSchema
from app.services.investment_service import InvestmentService
from app.utils.datetime_utils import iso_utc_now_naive


@dataclass(frozen=True)
class WalletApplicationError(Exception):
    message: str
    code: str
    status_code: int
    details: dict[str, Any] | None = None


class WalletApplicationService:
    def __init__(
        self,
        *,
        user_id: UUID,
        calculate_estimated_value: Callable[[dict[str, Any]], Any],
        get_market_price: Callable[[str | None], Any],
    ) -> None:
        self._user_id = user_id
        self._calculate_estimated_value = calculate_estimated_value
        self._get_market_price = get_market_price
        self._schema = WalletSchema()
        self._partial_schema = WalletSchema(partial=True)

    @classmethod
    def with_defaults(cls, user_id: UUID) -> WalletApplicationService:
        return cls(
            user_id=user_id,
            calculate_estimated_value=InvestmentService.calculate_estimated_value,
            get_market_price=lambda ticker: InvestmentService.get_market_price(
                ticker or ""
            ),
        )

    def create_entry(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            validated_data = self._schema.load(payload or {})
        except ValidationError as exc:
            raise WalletApplicationError(
                message="Dados inválidos",
                code="VALIDATION_ERROR",
                status_code=400,
                details={"messages": exc.messages},
            ) from exc

        estimated_value = self._calculate_estimated_value(validated_data)
        try:
            wallet = Wallet(
                user_id=self._user_id,
                name=validated_data["name"],
                value=validated_data.get("value"),
                estimated_value_on_create_date=estimated_value,
                ticker=validated_data.get("ticker"),
                quantity=validated_data.get("quantity"),
                asset_class=str(validated_data.get("asset_class", "custom")).lower(),
                annual_rate=validated_data.get("annual_rate"),
                register_date=validated_data.get("register_date", date.today()),
                target_withdraw_date=validated_data.get("target_withdraw_date"),
                should_be_on_wallet=validated_data["should_be_on_wallet"],
            )
            db.session.add(wallet)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            raise WalletApplicationError(
                message="Internal Server Error",
                code="INTERNAL_ERROR",
                status_code=500,
            ) from exc

        return self._serialize_wallet_item(wallet)

    def list_entries(self, *, page: int, per_page: int) -> dict[str, Any]:
        pagination = (
            Wallet.query.filter_by(user_id=self._user_id)
            .order_by(Wallet.created_at.desc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )
        return {
            "items": [self._serialize_wallet_item(item) for item in pagination.items],
            "pagination": {
                "total": pagination.total,
                "page": pagination.page,
                "per_page": pagination.per_page,
                "pages": pagination.pages,
            },
        }

    def get_entry(self, investment_id: UUID) -> dict[str, Any]:
        investment = self._get_owned_wallet(
            investment_id,
            forbidden_message=(
                "Você não tem permissão para visualizar este investimento."
            ),
        )
        return self._serialize_wallet_item(investment)

    def get_history(
        self,
        investment_id: UUID,
        *,
        page: int,
        per_page: int,
    ) -> dict[str, Any]:
        investment = self._get_owned_wallet(
            investment_id,
            forbidden_message=(
                "Você não tem permissão para ver o histórico deste investimento."
            ),
        )
        if per_page < 1 or per_page > 100:
            raise WalletApplicationError(
                message="Parâmetro 'per_page' inválido. Use 1-100.",
                code="VALIDATION_ERROR",
                status_code=400,
            )

        history = cast(list[dict[str, Any]], investment.history or [])

        def _sort_key(item: dict[str, Any]) -> tuple[Any, str]:
            return (item.get("originalQuantity", 0) or 0, item.get("changeDate", ""))

        sorted_history = sorted(history, key=_sort_key, reverse=True)
        total = len(sorted_history)
        start = (page - 1) * per_page
        end = start + per_page
        items = sorted_history[start:end]
        pages = (total + per_page - 1) // per_page if per_page and total else 0
        return {
            "items": items,
            "pagination": {
                "total": total,
                "page": page,
                "per_page": per_page,
                "page_size": per_page,
                "pages": pages,
                "has_next_page": end < total,
            },
        }

    def update_entry(
        self,
        investment_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        investment = self._get_owned_wallet(
            investment_id,
            forbidden_message="Você não tem permissão para editar este investimento.",
        )

        try:
            validated_data = self._partial_schema.load(payload or {}, partial=True)
        except ValidationError as exc:
            raise WalletApplicationError(
                message="Dados inválidos",
                code="VALIDATION_ERROR",
                status_code=400,
                details={"messages": exc.messages},
            ) from exc

        self._update_investment_history(investment, validated_data)
        self._apply_validated_fields(investment, validated_data)

        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            raise WalletApplicationError(
                message="Erro interno",
                code="INTERNAL_ERROR",
                status_code=500,
            ) from exc

        investment_data = self._serialize_wallet_item(investment)
        investment_data["history"] = investment.history
        return investment_data

    def delete_entry(
        self,
        investment_id: UUID,
        *,
        forbidden_message: str = (
            "Você não tem permissão para deletar este investimento."
        ),
    ) -> None:
        from app.extensions.audit_trail import record_entity_delete

        investment = self._get_owned_wallet(
            investment_id,
            forbidden_message=forbidden_message,
        )
        try:
            db.session.delete(investment)
            record_entity_delete(
                entity_type="wallet",
                entity_id=str(investment_id),
                actor_id=str(self._user_id),
            )
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            raise WalletApplicationError(
                message="Erro ao deletar investimento",
                code="INTERNAL_ERROR",
                status_code=500,
            ) from exc

    def _get_owned_wallet(
        self,
        investment_id: UUID,
        *,
        forbidden_message: str,
    ) -> Wallet:
        wallet = cast(Wallet | None, Wallet.query.filter_by(id=investment_id).first())
        if wallet is None:
            raise WalletApplicationError(
                message="Investimento não encontrado",
                code="NOT_FOUND",
                status_code=404,
            )
        if str(wallet.user_id) != str(self._user_id):
            raise WalletApplicationError(
                message=forbidden_message,
                code="FORBIDDEN",
                status_code=403,
            )
        return wallet

    def _update_investment_history(
        self,
        investment: Wallet,
        validated_data: dict[str, Any],
    ) -> None:
        old_quantity = investment.quantity
        old_estimated = investment.estimated_value_on_create_date
        old_value = investment.value

        changes: dict[str, Any] = {}
        if "quantity" in validated_data and validated_data["quantity"] != old_quantity:
            price = self._get_market_price(investment.ticker)
            changes = {
                "changeDate": iso_utc_now_naive(),
                "originalQuantity": old_quantity,
                "estimated_value_on_create_date": (
                    float(old_estimated)
                    if isinstance(old_estimated, Decimal)
                    else old_estimated
                ),
                "originalValue": (
                    float(price) if isinstance(price, (int, float, Decimal)) else price
                ),
            }
        elif "value" in validated_data and validated_data["value"] != old_value:
            changes = {
                "originalValue": (
                    float(old_value) if isinstance(old_value, Decimal) else old_value
                ),
                "changeDate": iso_utc_now_naive(),
            }

        if changes:
            history = cast(list[dict[str, Any]], investment.history or [])
            history.append(changes)
            investment.history = history

    def _apply_validated_fields(
        self,
        investment: Wallet,
        validated_data: dict[str, Any],
    ) -> None:
        for field, value in validated_data.items():
            if field == "asset_class" and value is not None:
                setattr(investment, field, str(value).lower())
                continue
            setattr(investment, field, value)

        recalc_data = {
            **validated_data,
            "ticker": investment.ticker,
            "value": investment.value,
            "quantity": investment.quantity,
        }
        investment.estimated_value_on_create_date = self._calculate_estimated_value(
            recalc_data
        )

    @staticmethod
    def _strip_contract_fields(item: dict[str, Any]) -> dict[str, Any]:
        if item.get("ticker") is None:
            item.pop("estimated_value_on_create_date", None)
            item.pop("ticker", None)
            item.pop("quantity", None)
        else:
            item.pop("value", None)
        return item

    def _serialize_wallet_item(self, wallet: Wallet) -> dict[str, Any]:
        return self._strip_contract_fields(self._schema.dump(wallet))
