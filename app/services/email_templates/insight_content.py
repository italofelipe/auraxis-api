"""Turn an AI insight payload into email-ready content (#1617).

``AIAdvisoryService.generate_financial_insights`` returns a payload whose
``items`` carry the actual analysis (``type``/``dimension``/``title``/
``message``/``evidence``). The insight emails embed that content instead of
only the truncated summary.

The extraction is deliberately defensive: insight emails are best-effort
side-effects of a batch job, so a malformed payload degrades to "no embedded
section" rather than raising and aborting the notification.

Usage::

    from app.services.email_templates.insight_content import insight_email_content

    content = insight_email_content(result)
    render_analysis_ready_email(..., items=content.items, suggestion=content.suggestion)
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# Keep the email skimmable: a handful of items, each a short paragraph.
_MAX_ITEMS = 3
_MAX_MESSAGE_CHARS = 240

# Item types that read as "do this next" — the first one is promoted to the
# highlighted suggestion line instead of sitting in the item list.
_SUGGESTION_TYPES = (
    "oportunidade_economia",
    "planejamento_meta",
    "savings_rate_gap",
)


@dataclass(frozen=True)
class InsightEmailContent:
    """Email-ready projection of an insight payload.

    ``items`` are ``(title, message)`` pairs rendered as the email body;
    ``suggestion`` is the highlighted call-to-action line (empty when the
    insight has no actionable item).
    """

    items: list[tuple[str, str]]
    suggestion: str


def _clean(value: object) -> str:
    """Collapse whitespace in a string field; non-strings become empty."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _truncate(text: str, limit: int = _MAX_MESSAGE_CHARS) -> str:
    """Cut on a word boundary so the email body stays bounded."""
    if len(text) <= limit:
        return text
    return text[: limit - 3].rsplit(" ", 1)[0].rstrip() + "..."


def insight_email_content(
    payload: Mapping[str, Any] | None,
    *,
    max_items: int = _MAX_ITEMS,
) -> InsightEmailContent:
    """Extract the items and suggestion an insight email should embed.

    Args:
        payload: The insight generation result. Anything that is not a mapping
            with a list of items yields empty content.
        max_items: Upper bound on embedded items (the suggestion is separate).

    Returns:
        InsightEmailContent — never raises.
    """
    entries = payload.get("items") if isinstance(payload, Mapping) else None
    if not isinstance(entries, list):
        return InsightEmailContent(items=[], suggestion="")

    items: list[tuple[str, str]] = []
    suggestion = ""
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        title = _clean(entry.get("title"))
        message = _clean(entry.get("message"))
        if not title or not message:
            continue
        if not suggestion and _clean(entry.get("type")) in _SUGGESTION_TYPES:
            suggestion = _truncate(message)
            continue
        items.append((title, _truncate(message)))

    return InsightEmailContent(items=items[:max_items], suggestion=suggestion)
