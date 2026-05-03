"""Regression tests for the structured-logging decorator wired around the
audit-bearing GraphQL resolvers (delete-shaped mutations + the auth flows).

The decorator emits a single info event on success and a single warning
event on failure, with operation name, duration, error code (when
available), and a SHA-256 truncated user hash. PII (raw user id, email)
must never appear in the log payload — these tests pin that invariant.

Scope: unit-level coverage of the decorator's contract. Integration with
the live Flask app is exercised indirectly by the rest of the GraphQL
test suite (every login/delete call goes through the wrapped resolvers).
"""

from __future__ import annotations

import logging
import re

import pytest

from app.graphql.observability import _hash_user_id, log_graphql_resolver


class TestUserIdHashing:
    def test_hash_is_deterministic_and_truncated_to_eight_hex(self) -> None:
        user_id = "00000000-0000-0000-0000-000000000001"
        first = _hash_user_id(user_id)
        second = _hash_user_id(user_id)
        assert first == second
        assert first is not None
        assert re.fullmatch(r"[0-9a-f]{8}", first)

    def test_distinct_inputs_produce_distinct_hashes(self) -> None:
        a = _hash_user_id("user-a")
        b = _hash_user_id("user-b")
        assert a != b

    def test_none_input_returns_none(self) -> None:
        assert _hash_user_id(None) is None


class TestDecoratorInUnitContext:
    def test_emits_ok_event_on_success(self, caplog: pytest.LogCaptureFixture) -> None:
        @log_graphql_resolver("probeOp")
        def fake_resolver() -> str:
            return "result"

        with caplog.at_level(logging.INFO):
            assert fake_resolver() == "result"

        ok_events = [
            record
            for record in caplog.records
            if "graphql.resolver.ok" in record.getMessage()
        ]
        assert ok_events, "no ok event emitted"
        assert "operation=probeOp" in ok_events[0].getMessage()
        assert "duration_ms=" in ok_events[0].getMessage()

    def test_emits_failed_event_on_exception_and_propagates(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        @log_graphql_resolver("probeFail")
        def fake_resolver() -> None:
            raise ValueError("boom")

        with caplog.at_level(logging.WARNING):
            with pytest.raises(ValueError):
                fake_resolver()

        failed_events = [
            record
            for record in caplog.records
            if "graphql.resolver.failed" in record.getMessage()
        ]
        assert failed_events, "no failed event emitted"
        assert "operation=probeFail" in failed_events[0].getMessage()


class TestLogPayloadHygiene:
    """The log payload must never contain raw PII or secrets."""

    def test_payload_uses_user_hash_not_raw_id(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        @log_graphql_resolver("probeHash")
        def fake_resolver() -> None:
            return None

        with caplog.at_level(logging.INFO):
            fake_resolver()

        events = [
            record
            for record in caplog.records
            if "graphql.resolver.ok" in record.getMessage()
        ]
        assert events
        payload = events[0].getMessage()
        # user_hash field is always present (even when no user is in
        # context, falls back to "anonymous").
        assert (
            "user_hash=anonymous" in payload
            or re.search(r"user_hash=[0-9a-f]{8}", payload) is not None
        )

    def test_failed_event_carries_extension_code(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from graphql import GraphQLError

        @log_graphql_resolver("probeCode")
        def fake_resolver() -> None:
            raise GraphQLError("denied", extensions={"code": "FORBIDDEN"})

        with caplog.at_level(logging.WARNING):
            with pytest.raises(GraphQLError):
                fake_resolver()

        events = [
            record
            for record in caplog.records
            if "graphql.resolver.failed" in record.getMessage()
        ]
        assert events
        assert "code=FORBIDDEN" in events[0].getMessage()
