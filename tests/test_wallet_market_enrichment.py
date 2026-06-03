"""Unit tests for wallet serialization market enrichment (#1442).

GET /wallet must expose cost_basis / current_value / change_percent so the
portfolio table can render Preço médio and Cotação atual instead of R$ 0,00.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.application.services.wallet_application_service import (
    WalletApplicationService,
)
from app.models.wallet import Wallet


def _service(price: float | None = None) -> WalletApplicationService:
    return WalletApplicationService(
        user_id=uuid4(),
        calculate_estimated_value=lambda _data: None,
        get_market_price=lambda _ticker: price,
    )


def _ticker_wallet() -> Wallet:
    return Wallet(
        user_id=uuid4(),
        name="PETROLEO BRASILEIRO S.A. PETROBRAS",
        ticker="PETR4",
        quantity=1000,
        estimated_value_on_create_date=Decimal("44480.00"),
        asset_class="stock",
        register_date=date(2016, 3, 30),
        should_be_on_wallet=True,
    )


def test_ticker_position_uses_live_quote_for_current_value() -> None:
    item = _service(price=50.0)._serialize_wallet_item(_ticker_wallet())

    assert item["cost_basis"] == 44480.0  # avg = 44.48 (web: cost_basis/quantity)
    assert item["current_value"] == 50000.0  # 1000 × 50.00
    assert item["change_percent"] == round((50000.0 - 44480.0) / 44480.0 * 100, 2)


def test_ticker_position_falls_back_to_cost_basis_without_quote() -> None:
    item = _service(price=None)._serialize_wallet_item(_ticker_wallet())

    # No live quote → current_value mirrors cost basis so the row never shows 0.
    assert item["cost_basis"] == 44480.0
    assert item["current_value"] == 44480.0
    assert item["change_percent"] == 0.0


def test_provider_failure_is_swallowed() -> None:
    def _boom(_ticker: str | None) -> float:
        raise RuntimeError("brapi down")

    service = WalletApplicationService(
        user_id=uuid4(),
        calculate_estimated_value=lambda _data: None,
        get_market_price=_boom,
    )

    item = service._serialize_wallet_item(_ticker_wallet())

    assert item["current_value"] == 44480.0  # graceful fallback, no exception


def test_non_ticker_asset_uses_stored_value() -> None:
    wallet = Wallet(
        user_id=uuid4(),
        name="Tesouro Selic",
        value=Decimal("1000.00"),
        ticker=None,
        asset_class="tesouro",
        annual_rate=Decimal("0.1100"),
        register_date=date(2024, 1, 1),
        should_be_on_wallet=True,
    )

    item = _service(price=999.0)._serialize_wallet_item(wallet)

    assert item["cost_basis"] == 1000.0
    assert item["current_value"] == 1000.0  # ignores quote for non-market assets
    assert item["change_percent"] == 0.0
