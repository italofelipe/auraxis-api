"""Custom GraphQL scalars used across the auraxis-api schema.

The :class:`DecimalScalar` exists because :class:`graphene.Float` collapses
values to IEEE 754 binary floats, which silently lose precision on monetary
amounts. The REST contract serialises monetary fields with
``marshmallow.fields.Decimal(as_string=True)`` (see ``app/schemas/``); this
scalar mirrors that behaviour so REST and GraphQL stay byte-equivalent.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import graphene
from graphql import GraphQLError
from graphql.language.ast import FloatValueNode, IntValueNode, StringValueNode


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        # bool is a subclass of int — be explicit and reject it.
        raise GraphQLError("DecimalScalar does not accept boolean values.")
    if isinstance(value, (int, float, str)):
        try:
            return Decimal(str(value))
        except InvalidOperation as exc:
            raise GraphQLError(f"Invalid decimal value: {value!r}") from exc
    raise GraphQLError(
        f"DecimalScalar cannot coerce value of type {type(value).__name__}."
    )


class DecimalScalar(graphene.Scalar):
    """Arbitrary-precision decimal serialised as a string.

    Output: always a string in fixed-point notation (no scientific exponent).
    Input: accepts string, int, float, or Decimal — coerced via ``Decimal(str(x))``.
    Null is preserved.
    """

    @staticmethod
    def serialize(value: Any) -> str | None:
        if value is None:
            return None
        return format(_to_decimal(value), "f")

    @staticmethod
    def parse_value(value: Any) -> Decimal | None:
        if value is None:
            return None
        return _to_decimal(value)

    @staticmethod
    def parse_literal(node: Any, _variables: Any = None) -> Decimal | None:
        if isinstance(node, (StringValueNode, IntValueNode, FloatValueNode)):
            try:
                return Decimal(node.value)
            except InvalidOperation as exc:
                raise GraphQLError(f"Invalid decimal literal: {node.value!r}") from exc
        raise GraphQLError("DecimalScalar literal must be a string, int, or float.")
