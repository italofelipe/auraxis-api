"""Tests for Bloco 2 model enrichments:
- Account: account_type, institution, initial_balance (#889)
- CreditCard: brand, limit_amount, closing_day, due_day (#889)
- Tag: color, icon, default seeds on registration (#890)
"""

from __future__ import annotations

import uuid

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _register_and_login(client, prefix: str) -> tuple[str, str]:
    """Register a new user and return (token, user_id_str)."""
    suffix = uuid.uuid4().hex[:8]
    email = f"{prefix}-{suffix}@email.com"
    password = "StrongPass@123"
    name = f"{prefix}-{suffix}"

    resp = client.post(
        "/auth/register",
        json={"name": name, "email": email, "password": password},
    )
    assert resp.status_code == 201, resp.get_json()

    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["token"], email


def _auth(token: str, contract: str = "v2") -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if contract:
        headers["X-API-Contract"] = contract
    return headers


# ===========================================================================
# Account tests
# ===========================================================================


def test_create_account_with_type_and_institution(client) -> None:
    token, _ = _register_and_login(client, "acc-enrich")

    resp = client.post(
        "/accounts",
        headers=_auth(token),
        json={
            "name": "Conta Corrente",
            "account_type": "checking",
            "institution": "Nubank",
            "initial_balance": "1500.00",
        },
    )
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    account = body["data"]["account"]
    assert account["account_type"] == "checking"
    assert account["institution"] == "Nubank"
    assert float(account["initial_balance"]) == 1500.0


def test_create_account_savings_type(client) -> None:
    token, _ = _register_and_login(client, "acc-savings")

    resp = client.post(
        "/accounts",
        headers=_auth(token),
        json={"name": "Poupança", "account_type": "savings"},
    )
    assert resp.status_code == 201
    account = resp.get_json()["data"]["account"]
    assert account["account_type"] == "savings"


def test_create_account_default_type_checking(client) -> None:
    token, _ = _register_and_login(client, "acc-default")

    resp = client.post(
        "/accounts",
        headers=_auth(token),
        json={"name": "Minha Conta"},
    )
    assert resp.status_code == 201
    account = resp.get_json()["data"]["account"]
    assert account["account_type"] == "checking"


def test_create_account_invalid_type_returns_400(client) -> None:
    token, _ = _register_and_login(client, "acc-invalid")

    resp = client.post(
        "/accounts",
        headers=_auth(token),
        json={"name": "Conta", "account_type": "invalid_type"},
    )
    assert resp.status_code == 400


def test_list_accounts_returns_enriched_fields(client) -> None:
    token, _ = _register_and_login(client, "acc-list")

    client.post(
        "/accounts",
        headers=_auth(token),
        json={"name": "Minha Conta", "account_type": "investment", "institution": "XP"},
    )

    resp = client.get("/accounts", headers=_auth(token))
    assert resp.status_code == 200
    accounts = resp.get_json()["data"]["accounts"]
    assert len(accounts) >= 1
    acc = accounts[0]
    assert "account_type" in acc
    assert "institution" in acc
    assert "initial_balance" in acc


def test_update_account_with_new_fields(client) -> None:
    token, _ = _register_and_login(client, "acc-update")

    create_resp = client.post(
        "/accounts",
        headers=_auth(token),
        json={"name": "Conta Original"},
    )
    account_id = create_resp.get_json()["data"]["account"]["id"]

    update_resp = client.put(
        f"/accounts/{account_id}",
        headers=_auth(token),
        json={
            "name": "Conta Atualizada",
            "account_type": "wallet",
            "institution": "Mercado Pago",
            "initial_balance": "200.00",
        },
    )
    assert update_resp.status_code == 200
    account = update_resp.get_json()["data"]["account"]
    assert account["account_type"] == "wallet"
    assert account["institution"] == "Mercado Pago"
    assert float(account["initial_balance"]) == 200.0


# ===========================================================================
# CreditCard tests
# ===========================================================================


def test_create_credit_card_with_brand_and_financials(client) -> None:
    token, _ = _register_and_login(client, "cc-enrich")

    resp = client.post(
        "/credit-cards",
        headers=_auth(token),
        json={
            "name": "Nubank Gold",
            "brand": "mastercard",
            "limit_amount": "5000.00",
            "closing_day": 20,
            "due_day": 5,
            "last_four_digits": "1234",
            "validity_date": "2030-12-31",
        },
    )
    assert resp.status_code == 201, resp.get_json()
    card = resp.get_json()["data"]["credit_card"]
    assert card["brand"] == "mastercard"
    assert float(card["limit_amount"]) == 5000.0
    assert card["closing_day"] == 20
    assert card["due_day"] == 5
    assert "last_four_digits" not in card
    assert "validity_date" not in card


def test_create_credit_card_invalid_brand_returns_400(client) -> None:
    token, _ = _register_and_login(client, "cc-invalid-brand")

    resp = client.post(
        "/credit-cards",
        headers=_auth(token),
        json={"name": "Cartão", "brand": "invalidbrand"},
    )
    assert resp.status_code == 400


def test_create_credit_card_invalid_closing_day_returns_400(client) -> None:
    token, _ = _register_and_login(client, "cc-invalid-day")

    resp = client.post(
        "/credit-cards",
        headers=_auth(token),
        json={"name": "Cartão", "closing_day": 30},
    )
    assert resp.status_code == 400


def test_list_credit_cards_returns_enriched_fields(client) -> None:
    token, _ = _register_and_login(client, "cc-list")

    client.post(
        "/credit-cards",
        headers=_auth(token),
        json={"name": "Meu Cartão", "brand": "visa", "limit_amount": "3000.00"},
    )

    resp = client.get("/credit-cards", headers=_auth(token))
    assert resp.status_code == 200
    cards = resp.get_json()["data"]["credit_cards"]
    assert len(cards) >= 1
    card = cards[0]
    assert "brand" in card
    assert "limit_amount" in card
    assert "closing_day" in card
    assert "due_day" in card
    assert "last_four_digits" not in card
    assert "validity_date" not in card


# ===========================================================================
# Tag color/icon tests (#890)
# ===========================================================================


def test_create_tag_with_color_and_icon(client) -> None:
    token, _ = _register_and_login(client, "tag-color")

    resp = client.post(
        "/tags",
        headers=_auth(token),
        json={"name": "Alimentação", "color": "#FF6B6B", "icon": "🍔"},
    )
    assert resp.status_code == 201, resp.get_json()
    tag = resp.get_json()["data"]["tag"]
    assert tag["color"] == "#FF6B6B"
    assert tag["icon"] == "🍔"


def test_create_tag_invalid_color_returns_400(client) -> None:
    token, _ = _register_and_login(client, "tag-bad-color")

    resp = client.post(
        "/tags",
        headers=_auth(token),
        json={"name": "Minha Tag", "color": "red"},
    )
    assert resp.status_code == 400


def test_create_tag_accepts_hex_with_alpha_and_normalizes(client) -> None:
    token, _ = _register_and_login(client, "tag-color-alpha")

    resp = client.post(
        "/tags",
        headers=_auth(token),
        json={"name": "Gastos fixos", "color": "#C21717FF", "icon": None},
    )
    assert resp.status_code == 201, resp.get_json()
    tag = resp.get_json()["data"]["tag"]
    assert tag["color"] == "#C21717"
    assert tag["icon"] is None


def test_update_tag_normalizes_alpha_hex(client) -> None:
    token, _ = _register_and_login(client, "tag-update-alpha")

    create = client.post(
        "/tags",
        headers=_auth(token),
        json={"name": "Lazer", "color": "#FFEAA7"},
    )
    tag_id = create.get_json()["data"]["tag"]["id"]

    resp = client.put(
        f"/tags/{tag_id}",
        headers=_auth(token),
        json={"name": "Lazer", "color": "#9B59B6CC"},
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["data"]["tag"]["color"] == "#9B59B6"


def test_tag_schema_accepts_six_and_eight_digit_hex() -> None:
    from marshmallow import ValidationError

    from app.schemas.tag_schema import TagSchema

    schema = TagSchema()

    # 6-digit canonical
    schema.load({"name": "ok-6", "color": "#FF6B6B"})
    # 8-digit with alpha
    schema.load({"name": "ok-8", "color": "#C21717FF"})
    # null color allowed
    schema.load({"name": "ok-null", "color": None})

    # Invalid forms still rejected
    for bad in ("red", "#XYZ", "#12345", "#1234567"):
        try:
            schema.load({"name": "bad", "color": bad})
        except ValidationError:
            continue
        raise AssertionError(f"expected ValidationError for color={bad!r}")


def test_list_tags_returns_color_and_icon(client) -> None:
    token, _ = _register_and_login(client, "tag-list-color")

    client.post(
        "/tags",
        headers=_auth(token),
        json={"name": "Transporte", "color": "#4ECDC4", "icon": "🚗"},
    )

    resp = client.get("/tags", headers=_auth(token))
    assert resp.status_code == 200
    tags = resp.get_json()["data"]["tags"]
    # Filter to the one we just created
    created = [t for t in tags if t["name"] == "Transporte"]
    # May have default tags too, just check structure
    for tag in tags:
        assert "color" in tag
        assert "icon" in tag
    assert len(created) >= 1
    assert created[0]["color"] == "#4ECDC4"


def test_registration_creates_8_default_tags(client) -> None:
    token, _ = _register_and_login(client, "tag-seed")

    resp = client.get("/tags", headers=_auth(token))
    assert resp.status_code == 200
    tags = resp.get_json()["data"]["tags"]
    assert len(tags) == 8


def test_default_tags_have_correct_colors_and_icons(client) -> None:
    token, _ = _register_and_login(client, "tag-seed-check")

    resp = client.get("/tags", headers=_auth(token))
    tags = resp.get_json()["data"]["tags"]

    tag_map = {t["name"]: t for t in tags}

    expected = [
        {"name": "Alimentação", "color": "#FF6B6B", "icon": "🍔"},
        {"name": "Transporte", "color": "#4ECDC4", "icon": "🚗"},
        {"name": "Moradia", "color": "#45B7D1", "icon": "🏠"},
        {"name": "Saúde", "color": "#96CEB4", "icon": "❤️"},
        {"name": "Lazer", "color": "#FFEAA7", "icon": "🎮"},
        {"name": "Educação", "color": "#DDA0DD", "icon": "📚"},
        {"name": "Investimentos", "color": "#98FB98", "icon": "📈"},
        {"name": "Outros", "color": "#D3D3D3", "icon": "📦"},
    ]

    for exp in expected:
        assert exp["name"] in tag_map, f"Tag '{exp['name']}' not found"
        tag = tag_map[exp["name"]]
        assert tag["color"] == exp["color"], f"Wrong color for {exp['name']}"
        assert tag["icon"] == exp["icon"], f"Wrong icon for {exp['name']}"


def test_update_tag_with_color_and_icon(client) -> None:
    token, _ = _register_and_login(client, "tag-update")

    # Get a default tag to update
    list_resp = client.get("/tags", headers=_auth(token))
    tags = list_resp.get_json()["data"]["tags"]
    tag_id = tags[0]["id"]

    resp = client.put(
        f"/tags/{tag_id}",
        headers=_auth(token),
        json={"name": "Nova Tag", "color": "#ABCDEF", "icon": "⭐"},
    )
    assert resp.status_code == 200
    tag = resp.get_json()["data"]["tag"]
    assert tag["color"] == "#ABCDEF"
    assert tag["icon"] == "⭐"
