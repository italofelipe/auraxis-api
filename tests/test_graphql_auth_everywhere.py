"""Regression tests asserting auth is enforced on every non-public GraphQL
operation.

The audit (2026-05-02) confirmed that every protected mutation/query calls
``get_current_user_required()`` today — but no test pinned that contract,
so a future mutation could regress silently. This module enumerates the
schema at runtime and verifies the authorization gate fires for every
mutation and every query that is not in the documented public allowlist.

If a new operation needs to be public, it must be added explicitly to
``DEFAULT_GRAPHQL_PUBLIC_QUERIES`` / ``DEFAULT_GRAPHQL_PUBLIC_MUTATIONS``.
That keeps the allowlist auditable and forces a deliberate review of any
unauthenticated surface.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.graphql.authorization import (
    DEFAULT_GRAPHQL_PUBLIC_MUTATIONS,
    DEFAULT_GRAPHQL_PUBLIC_QUERIES,
)
from app.graphql.mutations import Mutation
from app.graphql.queries import Query


def _to_camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part.capitalize() for part in tail)


def _protected_mutation_field_names() -> list[str]:
    fields = [_to_camel(name) for name in Mutation._meta.fields]
    return sorted(set(fields) - DEFAULT_GRAPHQL_PUBLIC_MUTATIONS)


def _protected_query_field_names() -> list[str]:
    fields = [_to_camel(name) for name in Query._meta.fields]
    return sorted(set(fields) - DEFAULT_GRAPHQL_PUBLIC_QUERIES)


def _post_unauth(client: Any, query: str) -> Any:
    return client.post("/graphql", json={"query": query})


def _first_error_code(response: Any) -> str | None:
    body = response.get_json() or {}
    errors = body.get("errors") or []
    if not errors:
        return None
    extensions = errors[0].get("extensions") or {}
    code = extensions.get("code")
    return str(code) if code is not None else None


@pytest.mark.parametrize("mutation_name", _protected_mutation_field_names())
def test_protected_mutation_requires_auth(client: Any, mutation_name: str) -> None:
    """Every mutation outside ``DEFAULT_GRAPHQL_PUBLIC_MUTATIONS`` must reject
    anonymous callers with a documented auth-required code at the
    authorization gate (before any field-level validation)."""

    query = f"mutation Probe {{ {mutation_name} {{ __typename }} }}"
    response = _post_unauth(client, query)
    code = _first_error_code(response)
    assert code in {
        "UNAUTHORIZED",
        "GRAPHQL_AUTH_REQUIRED",
    }, f"mutation {mutation_name} did not enforce auth — got code={code!r}"


@pytest.mark.parametrize("query_name", _protected_query_field_names())
def test_protected_query_requires_auth(client: Any, query_name: str) -> None:
    """Every query outside ``DEFAULT_GRAPHQL_PUBLIC_QUERIES`` must reject
    anonymous callers with a documented auth-required code."""

    query = f"query Probe {{ {query_name} {{ __typename }} }}"
    response = _post_unauth(client, query)
    code = _first_error_code(response)
    assert code in {
        "UNAUTHORIZED",
        "GRAPHQL_AUTH_REQUIRED",
    }, f"query {query_name} did not enforce auth — got code={code!r}"


def test_public_mutation_allowlist_is_intentional() -> None:
    """Pin the allowlist so regressions surface as a test diff and require a
    matching update to this assertion. Adding a new public mutation now
    requires both the allowlist update AND an explicit code change here,
    catching accidental exposure during review."""

    expected = {
        "registerUser",
        "login",
        "forgotPassword",
        "resetPassword",
        "resendConfirmationEmail",
        "confirmEmail",
    }
    assert DEFAULT_GRAPHQL_PUBLIC_MUTATIONS == expected


def test_public_query_allowlist_is_intentional() -> None:
    expected = {"__typename", "billingPlans", "installmentVsCashCalculate"}
    assert DEFAULT_GRAPHQL_PUBLIC_QUERIES == expected
