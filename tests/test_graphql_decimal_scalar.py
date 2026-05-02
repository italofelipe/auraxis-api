"""Regression tests for the GraphQL DecimalScalar.

The scalar exists to mirror the REST contract (``Decimal(as_string=True)``) and
to prevent silent precision loss in monetary fields. These tests pin the
contract: round-trip without precision loss and string output regardless of
input form.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from graphql import GraphQLError
from graphql.language.ast import FloatValueNode, IntValueNode, StringValueNode

from app.graphql.scalars import DecimalScalar


class TestDecimalScalarSerialize:
    def test_preserves_high_precision_decimal(self) -> None:
        value = Decimal("12345678901234.123456789")
        assert DecimalScalar.serialize(value) == "12345678901234.123456789"

    def test_preserves_value_above_one_billion(self) -> None:
        value = Decimal("9999999999.99")
        assert DecimalScalar.serialize(value) == "9999999999.99"

    def test_serialises_integer_input_as_string(self) -> None:
        assert DecimalScalar.serialize(42) == "42"

    def test_serialises_string_input_unchanged(self) -> None:
        assert DecimalScalar.serialize("0.10") == "0.10"

    def test_returns_none_for_none_input(self) -> None:
        assert DecimalScalar.serialize(None) is None

    def test_avoids_scientific_notation(self) -> None:
        value = Decimal("0.00000001")
        assert DecimalScalar.serialize(value) == "0.00000001"

    def test_rejects_boolean_input(self) -> None:
        with pytest.raises(GraphQLError):
            DecimalScalar.serialize(True)

    def test_rejects_unsupported_types(self) -> None:
        with pytest.raises(GraphQLError):
            DecimalScalar.serialize(object())


class TestDecimalScalarParseValue:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("1234567.89", Decimal("1234567.89")),
            (10, Decimal("10")),
            (0.5, Decimal("0.5")),
            (Decimal("99.99"), Decimal("99.99")),
        ],
    )
    def test_accepts_supported_inputs(self, raw: Any, expected: Decimal) -> None:
        assert DecimalScalar.parse_value(raw) == expected

    def test_returns_none_for_none(self) -> None:
        assert DecimalScalar.parse_value(None) is None

    def test_rejects_invalid_string(self) -> None:
        with pytest.raises(GraphQLError):
            DecimalScalar.parse_value("not-a-number")


class TestDecimalScalarParseLiteral:
    @pytest.mark.parametrize(
        "node,expected",
        [
            (StringValueNode(value="1234.56"), Decimal("1234.56")),
            (IntValueNode(value="10"), Decimal("10")),
            (FloatValueNode(value="0.10"), Decimal("0.10")),
        ],
    )
    def test_accepts_string_int_and_float_literals(
        self, node: Any, expected: Decimal
    ) -> None:
        assert DecimalScalar.parse_literal(node) == expected

    def test_rejects_invalid_literal(self) -> None:
        with pytest.raises(GraphQLError):
            DecimalScalar.parse_literal(StringValueNode(value="not-a-number"))
