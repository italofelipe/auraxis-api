import uuid
from datetime import UTC, date, datetime, timedelta


def _register_and_login(client, prefix: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    email = f"{prefix}-{suffix}@email.com"
    password = "StrongPass@123"

    register_response = client.post(
        "/auth/register",
        json={"name": f"{prefix}-{suffix}", "email": email, "password": password},
    )
    assert register_response.status_code == 201

    login_response = client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    assert login_response.status_code == 200
    return login_response.get_json()["token"]


def _auth_headers(token: str, contract: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if contract:
        headers["X-API-Contract"] = contract
    return headers


def _transaction_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": "Conta de água",
        "amount": "120.50",
        "type": "expense",
        "due_date": date.today().isoformat(),
    }
    payload.update(overrides)
    return payload


def test_transaction_installment_create_success(client) -> None:
    token = _register_and_login(client, "installment")
    response = client.post(
        "/transactions",
        headers=_auth_headers(token, "v2"),
        json={
            **_transaction_payload(),
            "amount": "300.00",
            "is_installment": True,
            "installment_count": 3,
        },
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["success"] is True
    transactions = body["data"]["transactions"]
    assert len(transactions) == 3
    assert transactions[0]["title"].endswith("(1/3)")
    assert transactions[1]["title"].endswith("(2/3)")
    assert transactions[2]["title"].endswith("(3/3)")


def test_transaction_update_requires_paid_at_when_paid(client) -> None:
    token = _register_and_login(client, "paid-at-required")
    created = client.post(
        "/transactions",
        headers=_auth_headers(token, "v2"),
        json=_transaction_payload(),
    )
    transaction_id = created.get_json()["data"]["transaction"][0]["id"]

    response = client.patch(
        f"/transactions/{transaction_id}",
        headers=_auth_headers(token, "v2"),
        json={"status": "paid"},
    )

    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_transaction_update_paid_at_without_paid_status(client) -> None:
    token = _register_and_login(client, "paid-at-status")
    created = client.post(
        "/transactions",
        headers=_auth_headers(token, "v2"),
        json=_transaction_payload(),
    )
    transaction_id = created.get_json()["data"]["transaction"][0]["id"]

    response = client.patch(
        f"/transactions/{transaction_id}",
        headers=_auth_headers(token, "v2"),
        json={"status": "pending", "paid_at": datetime.now(UTC).isoformat()},
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_transaction_update_paid_at_future_returns_400(client) -> None:
    token = _register_and_login(client, "paid-at-future")
    created = client.post(
        "/transactions",
        headers=_auth_headers(token, "v2"),
        json=_transaction_payload(),
    )
    transaction_id = created.get_json()["data"]["transaction"][0]["id"]
    future_paid_at = (datetime.now(UTC) + timedelta(days=2)).isoformat()

    response = client.patch(
        f"/transactions/{transaction_id}",
        headers=_auth_headers(token, "v2"),
        json={"status": "paid", "paid_at": future_paid_at},
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_transaction_create_persists_paid_at(client) -> None:
    """POST /transactions must not swallow a validated ``paid_at`` (#1659)."""
    token = _register_and_login(client, "create-paid-at")
    paid_at = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

    response = client.post(
        "/transactions",
        headers=_auth_headers(token, "v2"),
        json=_transaction_payload(status="paid", paid_at=paid_at),
    )

    assert response.status_code == 201
    created = response.get_json()["data"]["transaction"][0]
    assert created["paid_at"] is not None

    detail = client.get(
        f"/transactions/{created['id']}",
        headers=_auth_headers(token, "v2"),
    )
    assert detail.status_code == 200
    assert detail.get_json()["data"]["transaction"]["paid_at"] is not None


def test_transaction_create_installments_persist_paid_at(client) -> None:
    """The installment batch must persist ``paid_at`` too (#1659)."""
    token = _register_and_login(client, "create-paid-at-inst")
    paid_at = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

    response = client.post(
        "/transactions",
        headers=_auth_headers(token, "v2"),
        json=_transaction_payload(
            amount="300.00",
            status="paid",
            paid_at=paid_at,
            is_installment=True,
            installment_count=3,
        ),
    )

    assert response.status_code == 201
    transactions = response.get_json()["data"]["transactions"]
    assert len(transactions) == 3
    assert all(item["paid_at"] is not None for item in transactions)


def test_transaction_create_paid_status_without_paid_at_is_accepted(client) -> None:
    """Backward compatibility: create with status=paid and no paid_at stays 201."""
    token = _register_and_login(client, "create-paid-no-at")

    response = client.post(
        "/transactions",
        headers=_auth_headers(token, "v2"),
        json=_transaction_payload(status="paid"),
    )

    assert response.status_code == 201
    assert response.get_json()["data"]["transaction"][0]["paid_at"] is None


def test_transaction_create_paid_at_without_paid_status_returns_400(client) -> None:
    token = _register_and_login(client, "create-paid-at-status")

    response = client.post(
        "/transactions",
        headers=_auth_headers(token, "v2"),
        json=_transaction_payload(
            status="pending",
            paid_at=datetime.now(UTC).isoformat(),
        ),
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_transaction_create_paid_at_future_returns_400(client) -> None:
    token = _register_and_login(client, "create-paid-at-future")
    future_paid_at = (datetime.now(UTC) + timedelta(days=2)).isoformat()

    response = client.post(
        "/transactions",
        headers=_auth_headers(token, "v2"),
        json=_transaction_payload(status="paid", paid_at=future_paid_at),
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_transaction_create_paid_at_null_is_ignored(client) -> None:
    """An explicit ``paid_at: null`` must not trip the status invariant."""
    token = _register_and_login(client, "create-paid-at-null")

    response = client.post(
        "/transactions",
        headers=_auth_headers(token, "v2"),
        json={**_transaction_payload(), "paid_at": None},
    )

    assert response.status_code == 201
    assert response.get_json()["data"]["transaction"][0]["paid_at"] is None


def test_transaction_update_not_found_v2(client) -> None:
    token = _register_and_login(client, "update-not-found")
    missing_id = uuid.uuid4()

    response = client.patch(
        f"/transactions/{missing_id}",
        headers=_auth_headers(token, "v2"),
        json={"title": "novo"},
    )

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "NOT_FOUND"


def test_transaction_update_forbidden_v2(client) -> None:
    owner_token = _register_and_login(client, "owner")
    other_token = _register_and_login(client, "other")

    created = client.post(
        "/transactions",
        headers=_auth_headers(owner_token, "v2"),
        json=_transaction_payload(),
    )
    transaction_id = created.get_json()["data"]["transaction"][0]["id"]

    response = client.patch(
        f"/transactions/{transaction_id}",
        headers=_auth_headers(other_token, "v2"),
        json={"title": "hack"},
    )

    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "FORBIDDEN"


def test_transaction_delete_not_found_v2(client) -> None:
    token = _register_and_login(client, "delete-not-found")
    missing_id = uuid.uuid4()

    response = client.delete(
        f"/transactions/{missing_id}",
        headers=_auth_headers(token, "v2"),
    )

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "NOT_FOUND"


def test_transaction_delete_forbidden_v2(client) -> None:
    owner_token = _register_and_login(client, "delete-owner")
    other_token = _register_and_login(client, "delete-other")

    created = client.post(
        "/transactions",
        headers=_auth_headers(owner_token, "v2"),
        json=_transaction_payload(),
    )
    transaction_id = created.get_json()["data"]["transaction"][0]["id"]

    response = client.delete(
        f"/transactions/{transaction_id}",
        headers=_auth_headers(other_token, "v2"),
    )

    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "FORBIDDEN"


def test_transaction_deleted_list_v2(client) -> None:
    token = _register_and_login(client, "deleted-list")
    created = client.post(
        "/transactions",
        headers=_auth_headers(token, "v2"),
        json=_transaction_payload(),
    )
    transaction_id = created.get_json()["data"]["transaction"][0]["id"]

    deleted = client.delete(
        f"/transactions/{transaction_id}",
        headers=_auth_headers(token, "v2"),
    )
    assert deleted.status_code == 200

    response = client.get(
        "/transactions/deleted",
        headers=_auth_headers(token, "v2"),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert "deleted_transactions" in body["data"]
    assert len(body["data"]["deleted_transactions"]) >= 1


def test_transaction_summary_invalid_format_v2(client) -> None:
    token = _register_and_login(client, "summary-invalid")
    response = client.get(
        "/transactions/summary?month=invalid-format",
        headers=_auth_headers(token, "v2"),
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_transaction_create_recurring_requires_date_range(client) -> None:
    token = _register_and_login(client, "recurring-required-dates")
    response = client.post(
        "/transactions",
        headers=_auth_headers(token, "v2"),
        json={
            **_transaction_payload(),
            "is_recurring": True,
        },
    )

    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_transaction_create_recurring_due_date_must_be_inside_range(client) -> None:
    token = _register_and_login(client, "recurring-range")
    response = client.post(
        "/transactions",
        headers=_auth_headers(token, "v2"),
        json={
            **_transaction_payload(due_date=date.today().isoformat()),
            "is_recurring": True,
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
        },
    )

    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_transaction_update_recurring_invalid_date_range(client) -> None:
    token = _register_and_login(client, "recurring-update-range")
    created = client.post(
        "/transactions",
        headers=_auth_headers(token, "v2"),
        json={
            **_transaction_payload(),
            "is_recurring": True,
            "start_date": date.today().isoformat(),
            "end_date": (date.today() + timedelta(days=30)).isoformat(),
        },
    )
    assert created.status_code == 201
    transaction_id = created.get_json()["data"]["transaction"][0]["id"]

    response = client.patch(
        f"/transactions/{transaction_id}",
        headers=_auth_headers(token, "v2"),
        json={
            "start_date": (date.today() + timedelta(days=40)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
        },
    )

    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_transaction_put_compatibility_emits_deprecation_headers(client) -> None:
    token = _register_and_login(client, "put-compat")
    created = client.post(
        "/transactions",
        headers=_auth_headers(token, "v2"),
        json=_transaction_payload(),
    )
    assert created.status_code == 201
    transaction_id = created.get_json()["data"]["transaction"][0]["id"]

    response = client.put(
        f"/transactions/{transaction_id}",
        headers=_auth_headers(token, "v2"),
        json={"title": "Compatibilidade PUT"},
    )

    assert response.status_code == 200
    assert response.headers["Deprecation"] == "true"
    assert response.headers["X-Auraxis-Successor-Method"] == "PATCH"
    assert response.get_json()["data"]["transaction"]["title"] == "Compatibilidade PUT"


def test_transaction_patch_null_optional_fields_returns_200(client) -> None:
    """PATCH with null for optional fields must be accepted (bug #846)."""
    token = _register_and_login(client, "patch-null-fields")
    created = client.post(
        "/transactions",
        headers=_auth_headers(token, "v2"),
        json={
            **_transaction_payload(),
            "description": "Descrição inicial",
            "end_date": (date.today() + timedelta(days=30)).isoformat(),
        },
    )
    assert created.status_code == 201
    transaction_id = created.get_json()["data"]["transaction"][0]["id"]

    response = client.patch(
        f"/transactions/{transaction_id}",
        headers=_auth_headers(token, "v2"),
        json={
            "description": None,
            "end_date": None,
            "tag_id": None,
            "account_id": None,
            "credit_card_id": None,
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    transaction = body["data"]["transaction"]
    assert transaction["description"] is None
    assert transaction["end_date"] is None
    assert transaction["tag_id"] is None
    assert transaction["account_id"] is None
    assert transaction["credit_card_id"] is None


def test_transaction_patch_description_null_only_returns_200(client) -> None:
    """PATCH with only description=null must clear description (bug #846)."""
    token = _register_and_login(client, "patch-desc-null")
    created = client.post(
        "/transactions",
        headers=_auth_headers(token, "v2"),
        json={**_transaction_payload(), "description": "Descrição a limpar"},
    )
    assert created.status_code == 201
    transaction_id = created.get_json()["data"]["transaction"][0]["id"]

    response = client.patch(
        f"/transactions/{transaction_id}",
        headers=_auth_headers(token, "v2"),
        json={"description": None},
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["transaction"]["description"] is None


def test_transaction_patch_end_date_null_only_returns_200(client) -> None:
    """PATCH with only end_date=null must clear end_date on non-recurring (bug #846)."""
    token = _register_and_login(client, "patch-enddate-null")
    created = client.post(
        "/transactions",
        headers=_auth_headers(token, "v2"),
        json={
            **_transaction_payload(),
            "end_date": (date.today() + timedelta(days=60)).isoformat(),
        },
    )
    assert created.status_code == 201
    transaction_id = created.get_json()["data"]["transaction"][0]["id"]

    response = client.patch(
        f"/transactions/{transaction_id}",
        headers=_auth_headers(token, "v2"),
        json={"end_date": None},
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["transaction"]["end_date"] is None


def test_transaction_patch_start_date_null_returns_200(client) -> None:
    """PATCH with start_date=null must be accepted on non-recurring transactions."""
    token = _register_and_login(client, "patch-startdate-null")
    created = client.post(
        "/transactions",
        headers=_auth_headers(token, "v2"),
        json={
            **_transaction_payload(),
            "start_date": date.today().isoformat(),
        },
    )
    assert created.status_code == 201
    transaction_id = created.get_json()["data"]["transaction"][0]["id"]

    response = client.patch(
        f"/transactions/{transaction_id}",
        headers=_auth_headers(token, "v2"),
        json={"start_date": None},
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["transaction"]["start_date"] is None


def test_transaction_patch_recurring_to_non_recurring_clears_dates(client) -> None:
    """PATCH switching is_recurring=false alongside null dates must succeed."""
    token = _register_and_login(client, "patch-rec-to-nonrec")
    today = date.today()
    created = client.post(
        "/transactions",
        headers=_auth_headers(token, "v2"),
        json={
            **_transaction_payload(due_date=today.isoformat()),
            "is_recurring": True,
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=365)).isoformat(),
        },
    )
    assert created.status_code == 201
    transaction_id = created.get_json()["data"]["transaction"][0]["id"]

    response = client.patch(
        f"/transactions/{transaction_id}",
        headers=_auth_headers(token, "v2"),
        json={"is_recurring": False, "start_date": None, "end_date": None},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    transaction = body["data"]["transaction"]
    assert transaction["is_recurring"] is False
    assert transaction["start_date"] is None
    assert transaction["end_date"] is None


def test_transaction_patch_observation_null_v2_returns_200(client) -> None:
    """PATCH with observation=null on v2 contract must clear observation (regression #892)."""  # noqa: E501
    token = _register_and_login(client, "patch-obs-null-v2")
    created = client.post(
        "/transactions",
        headers=_auth_headers(token, "v2"),
        json={**_transaction_payload(), "observation": "Observação inicial"},
    )
    assert created.status_code == 201
    transaction_id = created.get_json()["data"]["transaction"][0]["id"]

    response = client.patch(
        f"/transactions/{transaction_id}",
        headers=_auth_headers(token, "v2"),
        json={"observation": None},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["data"]["transaction"]["observation"] is None


def test_transaction_patch_all_nullable_fields_null_v2_returns_200(client) -> None:
    """PATCH sending null for every nullable field with v2 contract must return 200.

    This is a regression test for the production bug where description and
    end_date (and observation) were rejected with VALIDATION_ERROR even though
    allow_none=True should have been set in TransactionSchema.
    """
    token = _register_and_login(client, "patch-all-nullable-v2")
    today = date.today()
    created = client.post(
        "/transactions",
        headers=_auth_headers(token, "v2"),
        json={
            **_transaction_payload(),
            "description": "Descrição de teste",
            "observation": "Observação de teste",
            "end_date": (today + timedelta(days=30)).isoformat(),
            "start_date": today.isoformat(),
        },
    )
    assert created.status_code == 201
    transaction_id = created.get_json()["data"]["transaction"][0]["id"]

    response = client.patch(
        f"/transactions/{transaction_id}",
        headers=_auth_headers(token, "v2"),
        json={
            "description": None,
            "observation": None,
            "end_date": None,
            "start_date": None,
            "tag_id": None,
            "account_id": None,
            "credit_card_id": None,
        },
    )

    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["success"] is True
    transaction = body["data"]["transaction"]
    assert transaction["description"] is None
    assert transaction["observation"] is None
    assert transaction["end_date"] is None
    assert transaction["start_date"] is None
    assert transaction["tag_id"] is None
    assert transaction["account_id"] is None
    assert transaction["credit_card_id"] is None
