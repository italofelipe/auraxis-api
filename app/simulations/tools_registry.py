"""Allowlist of `tool_id` values accepted by the canonical simulations endpoint.

This registry mirrors the catalog declared in
``auraxis-app/features/tools/services/tools-catalog.ts`` (and its web mirror).
Drift between the three is detected by ``scripts/check_tools_registry_parity.py``
which is run in CI.

When a new tool ships, add it here in the same PR that lands it on the app/web
catalog. Removing a tool here is a contract break — coordinate the migration
of historical simulations before doing so.
"""

from __future__ import annotations

# ── Canonical registry ────────────────────────────────────────────────
# Kept sorted for human review. The trailing comma is intentional so each
# additive change shows as a single-line diff.

TOOLS_REGISTRY: frozenset[str] = frozenset(
    {
        # Legacy snake_case ID still emitted by the existing installment-vs-cash
        # save flow (``InstallmentVsCashService.TOOL_ID``). Kept in the registry
        # so historical rows and the bespoke save endpoint keep working
        # alongside the canonical kebab-case id below. Remove after a data
        # migration that rewrites ``simulations.tool_id`` to the kebab form.
        "installment_vs_cash",
        # Salário & Trabalho
        "clt-vs-pj",
        "fgts-balance",
        "inss-ir-payroll",
        "mei-monthly",
        "overtime",
        "salary-net-clt",
        "salary-raise",
        "termination",
        "thirteenth-salary",
        "vacation",
        # Investimentos
        "broker-fees",
        "cdb-lci-lca",
        "compound-interest",
        "etf",
        "fii",
        "fire",
        "ipca-correction",
        "treasury",
        # Dívidas & Financiamento
        "cet-calculator",
        "consigned-loan",
        "credit-card-revolver",
        "debt-payoff",
        "loan-simulator",
        "mortgage",
        "vehicle-financing",
        # Imóvel
        "iptu",
        "itbi",
        "rent-vs-buy",
        "rental-yield",
        # Dia a dia
        "aposentadoria",
        "cost-of-lifestyle",
        "currency-converter",
        "desconto-markup",
        "emergency-fund",
        "fifty-thirty-twenty",
        "goal-simulator",
        "installment-vs-cash",
        "monthly-fuel",
        "salary-simulator",
        "split-bill",
        "subscription-audit",
    }
)


# Tool IDs kept for backwards compatibility with rows or callers from before
# the kebab-case canonical naming. Excluded from the catalog parity check so
# the app/web mirror does not need to ship them.
LEGACY_TOOL_IDS: frozenset[str] = frozenset({"installment_vs_cash"})


def is_known_tool(tool_id: str) -> bool:
    """Return ``True`` when ``tool_id`` exists in the canonical registry."""
    return tool_id in TOOLS_REGISTRY


def sorted_tool_ids() -> tuple[str, ...]:
    """Return the registry as a stable, sorted tuple (for CI parity diffs)."""
    return tuple(sorted(TOOLS_REGISTRY))


def canonical_tool_ids() -> frozenset[str]:
    """Return the registry minus legacy ids (used by the parity check)."""
    return TOOLS_REGISTRY - LEGACY_TOOL_IDS
