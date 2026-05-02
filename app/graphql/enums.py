"""GraphQL enum types mirroring the canonical REST validation sets.

Why: the REST contract validates ``status`` / ``type`` / ``asset_class`` /
``billing_cycle`` via ``Marshmallow validate.OneOf(...)``. Until this module
existed, the GraphQL schema accepted bare ``String`` for the same fields,
so a malformed client could push invalid values through GraphQL that REST
would have rejected. This module restores the parity for *inputs*.

Enum members use UPPERCASE names per GraphQL convention (clients write
``status: PAID`` rather than ``status: "paid"``); the underlying Python
value mirrors the REST string ("paid"). Resolvers must call
:func:`coerce_enum_value` before forwarding the kwargs to the service
layer, since the service consumes plain strings.

Output fields keep ``String`` for now, so REST and GraphQL responses stay
byte-identical. Migrating the output side is a follow-up tracked in the
audit umbrella (#1157).
"""

from __future__ import annotations

import enum
from typing import Any

import graphene

from app.models.subscription import BillingCycle, SubscriptionStatus
from app.models.transaction import TransactionStatus, TransactionType
from app.schemas.goal_schema import GOAL_STATUSES
from app.schemas.wallet_schema import ASSET_CLASSES

TransactionStatusEnum = graphene.Enum.from_enum(TransactionStatus)
TransactionTypeEnum = graphene.Enum.from_enum(TransactionType)
SubscriptionStatusEnum = graphene.Enum.from_enum(SubscriptionStatus)
SubscriptionBillingCycleEnum = graphene.Enum.from_enum(BillingCycle)


def _enum_from_strings(name: str, values: tuple[str, ...]) -> Any:
    members = {value.upper(): value for value in values}
    return graphene.Enum(name, list(members.items()))


GoalStatusEnum = _enum_from_strings("GoalStatus", tuple(GOAL_STATUSES))
WalletAssetClassEnum = _enum_from_strings(
    "WalletAssetClass", tuple(sorted(ASSET_CLASSES))
)


def coerce_enum_value(value: Any) -> Any:
    """Return the underlying string for a Python ``enum.Enum`` instance.

    Graphene resolvers receive Python enum instances when an Enum input is
    used. Service-layer code expects plain strings; this helper bridges
    the gap without scattering ``isinstance`` checks across resolvers.
    Pass-through for non-enum values (including ``None``).
    """

    if isinstance(value, enum.Enum):
        return value.value
    return value


def coerce_enum_kwargs(kwargs: dict[str, Any], *fields: str) -> dict[str, Any]:
    """In-place helper: replace enum values with their underlying string for
    the named ``fields``. Returns the same dict to allow chained use."""

    for field in fields:
        if field in kwargs:
            kwargs[field] = coerce_enum_value(kwargs[field])
    return kwargs
