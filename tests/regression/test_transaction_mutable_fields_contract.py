"""Regression: PATCH must not silently drop mutable transaction fields.

Bug history: ``auto_settle`` was added to ``TransactionSchema`` but not to the
``_MUTABLE_TRANSACTION_FIELDS`` registry consumed by ``_apply_transaction_updates``
(``app/application/services/transaction/query_helpers.py``). Because the update
loop skips any field not in that registry, PATCH silently ignored ``auto_settle``
until fix ``0d8dfbe``. This suite keeps the registry and the schema in agreement so
any future loadable field that is forgotten fails CI instead of being dropped at
runtime.
"""

from __future__ import annotations

from app.application.services.transaction.query_helpers import (
    _MUTABLE_TRANSACTION_FIELDS,
)
from app.models.transaction import Transaction
from app.schemas.transaction_schema import TransactionSchema

# Fields the API accepts at *creation* but intentionally does NOT allow mutating
# via PATCH. Recurrence cadence is fixed when the series is created; changing it
# after occurrences exist would desync the already-generated schedule. Anything
# listed here is a deliberate, reviewed decision — not a silent drop. New entries
# require justification in review.
_KNOWN_CREATE_ONLY_FIELDS = frozenset({"recurrence_interval", "recurrence_unit"})


def _loadable_schema_fields() -> set[str]:
    """Fields the transaction schema accepts on load (i.e. not ``dump_only``)."""
    return {
        name
        for name, field in TransactionSchema().fields.items()
        if not field.dump_only
    }


def test_mutable_fields_are_real_transaction_columns() -> None:
    """Every mutable field must map to a real Transaction column (no typos/drift)."""
    columns = set(Transaction.__table__.columns.keys())
    unknown = _MUTABLE_TRANSACTION_FIELDS - columns
    assert not unknown, (
        "_MUTABLE_TRANSACTION_FIELDS references columns that do not exist on the "
        f"Transaction model: {sorted(unknown)}"
    )


def test_mutable_fields_are_loadable_in_schema() -> None:
    """Every mutable field must be loadable via the transaction schema."""
    not_loadable = _MUTABLE_TRANSACTION_FIELDS - _loadable_schema_fields()
    assert not not_loadable, (
        "_MUTABLE_TRANSACTION_FIELDS lists fields the schema cannot load (they would "
        f"never reach _apply_transaction_updates): {sorted(not_loadable)}"
    )


def test_no_loadable_field_is_silently_dropped_on_patch() -> None:
    """Guards the original bug directly.

    A schema-loadable field that is missing from ``_MUTABLE_TRANSACTION_FIELDS`` is
    silently ignored by PATCH. Any new loadable field must be added either to the
    registry (to make it mutable) or to ``_KNOWN_CREATE_ONLY_FIELDS`` (to document
    it as create-only) — otherwise this test fails.
    """
    silently_dropped = (
        _loadable_schema_fields()
        - _MUTABLE_TRANSACTION_FIELDS
        - _KNOWN_CREATE_ONLY_FIELDS
    )
    assert not silently_dropped, (
        "These schema-loadable fields would be silently dropped by PATCH because "
        f"they are not in _MUTABLE_TRANSACTION_FIELDS: {sorted(silently_dropped)}. "
        "Add them to the registry (mutable) or to _KNOWN_CREATE_ONLY_FIELDS "
        "(create-only)."
    )


def test_auto_settle_is_mutable_regression() -> None:
    """Direct guard for the exact field from the original bug (fix 0d8dfbe)."""
    assert "auto_settle" in _MUTABLE_TRANSACTION_FIELDS
