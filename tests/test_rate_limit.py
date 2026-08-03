import uuid
from typing import Any

from app.middleware.rate_limit import RateLimiterService


def _register_and_login(client: Any, *, prefix: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    email = f"{prefix}-{suffix}@email.com"
    password = "StrongPass@123"

    register_response = client.post(
        "/auth/register",
        json={
            "name": f"{prefix}-{suffix}",
            "email": email,
            "password": password,
        },
    )
    assert register_response.status_code == 201

    login_response = client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    assert login_response.status_code == 200
    return str(login_response.get_json()["token"])


def _rate_limiter(client: Any) -> RateLimiterService:
    limiter = client.application.extensions.get("rate_limiter")
    assert isinstance(limiter, RateLimiterService)
    return limiter


def test_rate_limit_blocks_auth_after_threshold(client: Any) -> None:
    limiter = _rate_limiter(client)
    limiter.set_rule("auth", limit=2, window_seconds=60)

    for index in range(2):
        suffix = uuid.uuid4().hex[:8]
        response = client.post(
            "/auth/register",
            json={
                "name": f"rate-user-{index}-{suffix}",
                "email": f"rate-auth-{index}-{suffix}@email.com",
                "password": "StrongPass@123",
            },
        )
        assert response.status_code == 201

    blocked_response = client.post(
        "/auth/register",
        json={
            "name": "blocked-user",
            "email": f"blocked-{uuid.uuid4().hex[:8]}@email.com",
            "password": "StrongPass@123",
        },
    )

    assert blocked_response.status_code == 429
    body = blocked_response.get_json()
    assert body["error"] == "RATE_LIMIT_EXCEEDED"
    assert body["details"]["rule"] == "auth"
    assert blocked_response.headers["X-RateLimit-Rule"] == "auth"
    assert blocked_response.headers["Retry-After"]


def test_rate_limit_isolated_by_user_for_transactions(client: Any) -> None:
    limiter = _rate_limiter(client)
    limiter.set_rule("transactions", limit=1, window_seconds=60)

    user_one_token = _register_and_login(client, prefix="transactions-rate-1")
    user_two_token = _register_and_login(client, prefix="transactions-rate-2")

    user_one_headers = {
        "Authorization": f"Bearer {user_one_token}",
        "X-API-Contract": "v2",
    }
    user_two_headers = {
        "Authorization": f"Bearer {user_two_token}",
        "X-API-Contract": "v2",
    }

    first_user_one = client.get("/transactions/list", headers=user_one_headers)
    assert first_user_one.status_code == 200

    first_user_two = client.get("/transactions/list", headers=user_two_headers)
    assert first_user_two.status_code == 200

    blocked_user_one = client.get("/transactions/list", headers=user_one_headers)
    assert blocked_user_one.status_code == 429
    blocked_body = blocked_user_one.get_json()
    assert blocked_body["success"] is False
    assert blocked_body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert blocked_body["error"]["details"]["rule"] == "transactions"
    assert blocked_user_one.headers["X-RateLimit-Rule"] == "transactions"


def test_rate_limit_blocks_graphql_transport_after_threshold(client: Any) -> None:
    limiter = _rate_limiter(client)
    limiter.set_rule("graphql", limit=2, window_seconds=60)

    query_payload = {"query": "query { __typename }"}
    first = client.post("/graphql", json=query_payload)
    second = client.post("/graphql", json=query_payload)
    blocked = client.post("/graphql", json=query_payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert blocked.status_code == 429
    blocked_body = blocked.get_json()
    assert blocked_body["error"] == "RATE_LIMIT_EXCEEDED"
    assert blocked_body["details"]["rule"] == "graphql"
    assert blocked.headers["X-RateLimit-Rule"] == "graphql"


def test_graphql_mutation_uses_stricter_rule(client: Any) -> None:
    limiter = _rate_limiter(client)
    limiter.set_rule("graphql_mutation", limit=1, window_seconds=60)
    limiter.set_rule("graphql", limit=100, window_seconds=60)

    mutation_payload = {
        "query": 'mutation { login(email: "a@b.com", password: "x") { token } }'
    }
    first = client.post("/graphql", json=mutation_payload)
    blocked = client.post("/graphql", json=mutation_payload)

    assert first.status_code == 200
    assert blocked.status_code == 429
    blocked_body = blocked.get_json()
    assert blocked_body["details"]["rule"] == "graphql_mutation"
    assert blocked.headers["X-RateLimit-Rule"] == "graphql_mutation"


def test_graphql_query_does_not_use_mutation_rule(client: Any) -> None:
    limiter = _rate_limiter(client)
    limiter.set_rule("graphql_mutation", limit=1, window_seconds=60)
    limiter.set_rule("graphql", limit=100, window_seconds=60)

    query_payload = {"query": "query { __typename }"}
    for _ in range(3):
        resp = client.post("/graphql", json=query_payload)
        assert resp.status_code == 200
        assert resp.headers.get("X-RateLimit-Rule") == "graphql"


def test_checkout_uses_dedicated_tier_not_the_lenient_default(client: Any) -> None:
    """POST /subscriptions/checkout must resolve to the `checkout` tier.

    Before #1632 it fell through to `default` (300/window). Each checkout holds
    one of the four gunicorn threads on a blocking call to the PSP, so the
    lenient tier made it a cheap way to starve the whole API.
    """
    limiter = _rate_limiter(client)
    limiter.set_rule("checkout", limit=10, window_seconds=60)

    response = client.post("/subscriptions/checkout", json={})

    assert response.headers.get("X-RateLimit-Rule") == "checkout"


def test_checkout_blocks_after_threshold(client: Any) -> None:
    """The 11th call in the window is refused — the AC of #1632."""
    limiter = _rate_limiter(client)
    limiter.set_rule("checkout", limit=10, window_seconds=60)

    statuses = [
        client.post("/subscriptions/checkout", json={}).status_code for _ in range(10)
    ]
    blocked = client.post("/subscriptions/checkout", json={})

    assert 429 not in statuses
    assert blocked.status_code == 429
    assert blocked.get_json()["details"]["rule"] == "checkout"


def test_checkout_tier_does_not_shadow_the_webhook_tier(client: Any) -> None:
    """Sibling prefixes under /subscriptions must keep separate buckets.

    A regression here is silent and expensive: the provider's retries would be
    refused by a budget spent on checkouts, and a refused webhook means someone
    paid without receiving Premium.
    """
    limiter = _rate_limiter(client)
    limiter.set_rule("checkout", limit=1, window_seconds=60)
    limiter.set_rule("webhook", limit=60, window_seconds=60)

    client.post("/subscriptions/checkout", json={})
    exhausted = client.post("/subscriptions/checkout", json={})
    webhook = client.post("/subscriptions/webhook/asaas", json={})

    assert exhausted.status_code == 429
    assert webhook.status_code != 429
    assert webhook.headers.get("X-RateLimit-Rule") == "webhook"
