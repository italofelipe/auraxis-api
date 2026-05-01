"""Integration tests for the canonical generic /simulations endpoint (#1128).

Complements ``test_simulation_contract.py`` (legacy J7 contract) with
coverage for the new contractual rules introduced by DEC-196:

- ``tool_id`` validated against ``TOOLS_REGISTRY``
- Optional ``metadata`` field round-trips
- ``GET`` accepts ``tool_id`` filter
- Body size cap returns 413
- Generic GraphQL ``simulations`` and ``simulation`` queries return user data
"""

from __future__ import annotations

import json
import uuid
from typing import Any

UNKNOWN_TOOL_ID = "definitely-not-a-real-tool"
KNOWN_TOOL_ID = "compound-interest"


def _register_and_login(client, *, prefix: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    email = f"{prefix}-{suffix}@email.com"
    password = "StrongPass@123"
    reg = client.post(
        "/auth/register",
        json={"name": f"user-{suffix}", "email": email, "password": password},
    )
    assert reg.status_code == 201
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    return login.get_json()["token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tool_id": KNOWN_TOOL_ID,
        "rule_version": "2026.04",
        "inputs": {"initial": 1000, "monthly": 500, "rate": 12, "months": 120},
        "result": {"final": 124378.51, "interest": 63378.51},
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# tool_id registry validation
# ---------------------------------------------------------------------------


def test_unknown_tool_id_is_rejected(client) -> None:
    token = _register_and_login(client, prefix="sim-reg-unknown")
    resp = client.post(
        "/simulations",
        json=_payload(tool_id=UNKNOWN_TOOL_ID),
        headers=_auth(token),
    )
    assert resp.status_code == 400
    body = resp.get_json()
    # Validation error envelope (legacy contract) carries the offending field.
    assert "tool_id" in json.dumps(body)


def test_known_tool_id_is_accepted(client) -> None:
    token = _register_and_login(client, prefix="sim-reg-known")
    resp = client.post("/simulations", json=_payload(), headers=_auth(token))
    assert resp.status_code == 201
    assert resp.get_json()["simulation"]["tool_id"] == KNOWN_TOOL_ID


def test_aposentadoria_tool_id_is_accepted(client) -> None:
    token = _register_and_login(client, prefix="sim-reg-apos")
    resp = client.post(
        "/simulations",
        json=_payload(tool_id="aposentadoria"),
        headers=_auth(token),
    )
    assert resp.status_code == 201
    assert resp.get_json()["simulation"]["tool_id"] == "aposentadoria"


def test_desconto_markup_tool_id_is_accepted(client) -> None:
    token = _register_and_login(client, prefix="sim-reg-dm")
    resp = client.post(
        "/simulations",
        json=_payload(tool_id="desconto-markup"),
        headers=_auth(token),
    )
    assert resp.status_code == 201
    assert resp.get_json()["simulation"]["tool_id"] == "desconto-markup"


# ---------------------------------------------------------------------------
# inputs / result must be JSON objects
# ---------------------------------------------------------------------------


def test_inputs_must_be_json_object(client) -> None:
    token = _register_and_login(client, prefix="sim-inputs-bad")
    resp = client.post(
        "/simulations",
        json=_payload(inputs="not-an-object"),
        headers=_auth(token),
    )
    assert resp.status_code == 400


def test_result_must_be_json_object(client) -> None:
    token = _register_and_login(client, prefix="sim-result-bad")
    resp = client.post(
        "/simulations",
        json=_payload(result=[1, 2, 3]),
        headers=_auth(token),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# metadata field round-trip
# ---------------------------------------------------------------------------


def test_metadata_round_trips(client) -> None:
    token = _register_and_login(client, prefix="sim-meta")
    metadata = {"label": "Cenário conservador", "notes": "rebalancing yearly"}
    resp = client.post(
        "/simulations",
        json=_payload(metadata=metadata),
        headers=_auth(token),
    )
    assert resp.status_code == 201
    sim = resp.get_json()["simulation"]
    assert sim["metadata"] == metadata


def test_metadata_optional_when_omitted(client) -> None:
    token = _register_and_login(client, prefix="sim-meta-omit")
    resp = client.post("/simulations", json=_payload(), headers=_auth(token))
    assert resp.status_code == 201
    sim = resp.get_json()["simulation"]
    assert sim.get("metadata") is None


def test_metadata_must_be_object_when_present(client) -> None:
    token = _register_and_login(client, prefix="sim-meta-bad")
    resp = client.post(
        "/simulations",
        json=_payload(metadata="not-an-object"),
        headers=_auth(token),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# tool_id filter on the list endpoint
# ---------------------------------------------------------------------------


def test_list_filter_by_tool_id_returns_matching_only(client) -> None:
    token = _register_and_login(client, prefix="sim-filter")
    client.post(
        "/simulations",
        json=_payload(tool_id="compound-interest"),
        headers=_auth(token),
    )
    client.post(
        "/simulations",
        json=_payload(tool_id="cdb-lci-lca"),
        headers=_auth(token),
    )
    resp = client.get(
        "/simulations?tool_id=compound-interest",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    items = resp.get_json()["items"]
    assert len(items) == 1
    assert items[0]["tool_id"] == "compound-interest"


# ---------------------------------------------------------------------------
# Body size cap (16 KB)
# ---------------------------------------------------------------------------


def test_body_too_large_returns_413(client) -> None:
    token = _register_and_login(client, prefix="sim-big")
    # Build an inputs dict that pushes the body well past 16 KB.
    bloated_inputs = {f"k{i}": "x" * 50 for i in range(500)}
    resp = client.post(
        "/simulations",
        json=_payload(inputs=bloated_inputs),
        headers=_auth(token),
    )
    assert resp.status_code == 413
    assert resp.get_json()["error"] == "PAYLOAD_TOO_LARGE"


# ---------------------------------------------------------------------------
# GraphQL parity (queries only — CRUD mutations are REST-canonical, ADR-0002)
# ---------------------------------------------------------------------------


def _gql(client, token: str, query: str, variables: dict[str, Any] | None = None):
    return client.post(
        "/graphql",
        json={"query": query, "variables": variables or {}},
        headers={**_auth(token), "Content-Type": "application/json"},
    )


def test_graphql_simulations_query_returns_user_simulations(client) -> None:
    token = _register_and_login(client, prefix="gql-list")
    save = client.post("/simulations", json=_payload(), headers=_auth(token))
    saved_id = save.get_json()["simulation"]["id"]

    resp = _gql(
        client,
        token,
        """
        query { simulations { items { id toolId } total page perPage } }
        """,
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert "errors" not in body, body
    listing = body["data"]["simulations"]
    assert listing["total"] >= 1
    assert any(item["id"] == saved_id for item in listing["items"])


def test_graphql_simulations_filter_by_tool_id(client) -> None:
    token = _register_and_login(client, prefix="gql-filter")
    client.post(
        "/simulations",
        json=_payload(tool_id="compound-interest"),
        headers=_auth(token),
    )
    client.post(
        "/simulations",
        json=_payload(tool_id="cdb-lci-lca"),
        headers=_auth(token),
    )
    resp = _gql(
        client,
        token,
        'query { simulations(toolId: "compound-interest") { items { toolId } } }',
    )
    assert resp.status_code == 200
    items = resp.get_json()["data"]["simulations"]["items"]
    assert len(items) == 1
    assert items[0]["toolId"] == "compound-interest"


def test_graphql_simulation_detail_returns_owned_record(client) -> None:
    token = _register_and_login(client, prefix="gql-detail")
    save = client.post("/simulations", json=_payload(), headers=_auth(token))
    saved_id = save.get_json()["simulation"]["id"]

    resp = _gql(
        client,
        token,
        "query Q($id: UUID!) { simulation(id: $id) { id toolId } }",
        {"id": saved_id},
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]["simulation"]
    assert data["id"] == saved_id
    assert data["toolId"] == KNOWN_TOOL_ID
