from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import selectinload

from app.extensions.database import db
from app.models.wallet import Wallet
from app.services.investment_operation_service import (
    InvestmentOperationError,
    InvestmentOperationService,
)
from app.services.investment_service import InvestmentService

FIXED_INCOME_ASSET_CLASSES = {"cdb", "cdi", "lci", "lca", "tesouro"}


class PortfolioValuationService:
    def __init__(self, user_id: UUID) -> None:
        self.user_id = user_id
        self._operations_service = InvestmentOperationService(user_id)

    def get_investment_current_valuation(self, investment_id: UUID) -> dict[str, Any]:
        wallet = self._operations_service.get_owned_investment(investment_id)
        return self._build_item(wallet)

    def get_portfolio_current_valuation(self) -> dict[str, Any]:
        # PERF-GAP-02: selectinload avoids N+1 — _build_item accesses
        # wallet.operations for every wallet in the list.
        wallets: list[Wallet] = (
            db.session.query(Wallet)
            .filter_by(user_id=self.user_id)
            .options(selectinload(Wallet.operations))
            .all()
        )
        items = [self._build_item(wallet) for wallet in wallets]
        total_current_value = sum(
            (Decimal(item["current_value"]) for item in items), Decimal("0")
        )
        total_invested_amount = sum(
            (Decimal(item["invested_amount"]) for item in items), Decimal("0")
        )
        total_profit_loss = total_current_value - total_invested_amount
        total_profit_loss_percent = (
            (total_profit_loss / total_invested_amount) * Decimal("100")
            if total_invested_amount > 0
            else Decimal("0")
        )
        market_data_items = sum(
            1 for item in items if item["valuation_source"] == "brapi_market_price"
        )
        return {
            "summary": {
                "total_investments": len(items),
                "with_market_data": market_data_items,
                "without_market_data": len(items) - market_data_items,
                "total_invested_amount": str(total_invested_amount),
                "total_current_value": str(total_current_value),
                "total_profit_loss": str(total_profit_loss),
                "total_profit_loss_percent": str(total_profit_loss_percent),
            },
            "items": items,
        }

    def _build_item(self, wallet: Wallet) -> dict[str, Any]:
        has_operations = bool(wallet.operations)
        operation_quantity, operation_cost_basis = self._resolve_operations_position(
            wallet
        )

        base_quantity = (
            Decimal(str(wallet.quantity)) if wallet.quantity is not None else None
        )
        effective_quantity = (
            operation_quantity if has_operations else (base_quantity or Decimal("1"))
        )
        asset_class = str(wallet.asset_class or "custom").lower()

        current_value: Decimal
        invested_amount: Decimal
        valuation_source: str
        market_price: float | None
        if wallet.ticker:
            current_value, invested_amount, valuation_source, market_price = (
                self._build_ticker_valuation(
                    wallet=wallet,
                    effective_quantity=effective_quantity,
                    has_operations=has_operations,
                    operation_cost_basis=operation_cost_basis,
                )
            )
        elif (
            asset_class in FIXED_INCOME_ASSET_CLASSES and wallet.annual_rate is not None
        ):
            current_value, invested_amount, valuation_source, market_price = (
                self._build_fixed_income_valuation(wallet, base_quantity)
            )
        else:
            current_value, invested_amount, valuation_source, market_price = (
                self._build_manual_valuation(wallet, base_quantity)
            )

        unit_price = (
            (current_value / effective_quantity)
            if effective_quantity > 0
            else Decimal("0")
        )
        profit_loss_amount = current_value - invested_amount
        profit_loss_percent = (
            (profit_loss_amount / invested_amount) * Decimal("100")
            if invested_amount > 0
            else Decimal("0")
        )

        return {
            "investment_id": str(wallet.id),
            "name": wallet.name,
            "asset_class": asset_class,
            "annual_rate": (
                str(wallet.annual_rate) if wallet.annual_rate is not None else None
            ),
            "ticker": wallet.ticker,
            "should_be_on_wallet": wallet.should_be_on_wallet,
            "quantity": str(effective_quantity),
            "unit_price": str(unit_price),
            "invested_amount": str(invested_amount),
            "current_value": str(current_value),
            "profit_loss_amount": str(profit_loss_amount),
            "profit_loss_percent": str(profit_loss_percent),
            "market_price": str(market_price) if market_price is not None else None,
            "valuation_source": valuation_source,
            "uses_operations_quantity": has_operations,
        }

    def _resolve_operations_position(self, wallet: Wallet) -> tuple[Decimal, Decimal]:
        if not wallet.operations:
            return Decimal("0"), Decimal("0")
        try:
            position = self._operations_service.get_position(wallet.id)
            return (
                Decimal(position["current_quantity"]),
                Decimal(position["current_cost_basis"]),
            )
        except InvestmentOperationError:
            return Decimal("0"), Decimal("0")

    def _build_ticker_valuation(
        self,
        wallet: Wallet,
        effective_quantity: Decimal,
        has_operations: bool,
        operation_cost_basis: Decimal,
    ) -> tuple[Decimal, Decimal, str, float | None]:
        market_price = InvestmentService.get_market_price(wallet.ticker)
        invested_amount = self._resolve_invested_amount_from_operations(
            wallet, has_operations, operation_cost_basis
        )
        if market_price is not None:
            current_value = Decimal(str(market_price)) * effective_quantity
            return current_value, invested_amount, "brapi_market_price", market_price
        if has_operations and operation_cost_basis > 0:
            return operation_cost_basis, invested_amount, "fallback_cost_basis", None
        if wallet.estimated_value_on_create_date is not None:
            return (
                Decimal(str(wallet.estimated_value_on_create_date)),
                invested_amount,
                "fallback_estimated_on_create_date",
                None,
            )
        # Last resort: the user-entered value. A priced holding must never
        # collapse to R$0 just because the live quote is unavailable (#1546).
        if wallet.value is not None:
            return (
                Decimal(str(wallet.value)),
                invested_amount,
                "manual_value",
                None,
            )
        return Decimal("0"), invested_amount, "manual_value", None

    def _build_fixed_income_valuation(
        self, wallet: Wallet, base_quantity: Decimal | None
    ) -> tuple[Decimal, Decimal, str, None]:
        invested_amount = self._resolve_base_invested_amount(wallet, base_quantity)
        days = max((date.today() - wallet.register_date).days, 0)
        annual_rate = Decimal(str(wallet.annual_rate)) / Decimal("100")
        growth_factor = (Decimal("1") + annual_rate) ** (Decimal(days) / Decimal("365"))
        current_value = invested_amount * growth_factor
        return current_value, invested_amount, "fixed_income_projection", None

    def _build_manual_valuation(
        self, wallet: Wallet, base_quantity: Decimal | None
    ) -> tuple[Decimal, Decimal, str, None]:
        invested_amount = self._resolve_base_invested_amount(wallet, base_quantity)
        if invested_amount > 0:
            return invested_amount, invested_amount, "manual_value", None
        if wallet.estimated_value_on_create_date is not None:
            estimated_value = Decimal(str(wallet.estimated_value_on_create_date))
            return (
                estimated_value,
                invested_amount,
                "fallback_estimated_on_create_date",
                None,
            )
        return Decimal("0"), invested_amount, "manual_value", None

    @staticmethod
    def _resolve_invested_amount_from_operations(
        wallet: Wallet, has_operations: bool, operation_cost_basis: Decimal
    ) -> Decimal:
        if has_operations and operation_cost_basis > 0:
            return operation_cost_basis
        if wallet.estimated_value_on_create_date is not None:
            return Decimal(str(wallet.estimated_value_on_create_date))
        return Decimal("0")

    @staticmethod
    def _resolve_base_invested_amount(
        wallet: Wallet, base_quantity: Decimal | None
    ) -> Decimal:
        if wallet.value is not None and base_quantity is not None:
            return Decimal(str(wallet.value)) * base_quantity
        if wallet.value is not None:
            return Decimal(str(wallet.value))
        if wallet.estimated_value_on_create_date is not None:
            return Decimal(str(wallet.estimated_value_on_create_date))
        return Decimal("0")
