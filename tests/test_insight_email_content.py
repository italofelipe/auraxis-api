"""Tests for the insight → email content extractor (#1617).

The AI insight payload (``AIAdvisoryService.generate_financial_insights``)
carries ``items`` that the insight emails must embed. This module covers the
extraction contract: which items become the body, which one becomes the
highlighted suggestion, and the tolerance to malformed payloads — the emails
are best-effort, so a broken payload must degrade to "no section", never raise.
"""

from __future__ import annotations

from typing import Any

from app.services.email_templates.insight_content import insight_email_content


def _item(
    *,
    item_type: str = "gasto_elevado",
    title: str = "Delivery subiu 34%",
    message: str = "Você gastou R$ 620 com delivery, R$ 160 acima do mês anterior.",
) -> dict[str, Any]:
    return {
        "type": item_type,
        "dimension": "spending",
        "title": title,
        "message": message,
        "evidence": ["spending.by_category.delivery"],
    }


class TestItemExtraction:
    def test_extracts_title_and_message_pairs(self) -> None:
        payload = {"summary": "Resumo.", "items": [_item()]}
        content = insight_email_content(payload)
        assert content.items == [
            (
                "Delivery subiu 34%",
                "Você gastou R$ 620 com delivery, R$ 160 acima do mês anterior.",
            )
        ]

    def test_preserves_payload_order(self) -> None:
        payload = {
            "items": [
                _item(title="Primeiro"),
                _item(title="Segundo"),
                _item(title="Terceiro"),
            ]
        }
        content = insight_email_content(payload)
        assert [title for title, _ in content.items] == [
            "Primeiro",
            "Segundo",
            "Terceiro",
        ]

    def test_caps_the_number_of_items(self) -> None:
        payload = {"items": [_item(title=f"Item {i}") for i in range(10)]}
        content = insight_email_content(payload, max_items=2)
        assert len(content.items) == 2

    def test_default_cap_keeps_the_email_short(self) -> None:
        payload = {"items": [_item(title=f"Item {i}") for i in range(10)]}
        content = insight_email_content(payload)
        assert 0 < len(content.items) <= 4

    def test_truncates_long_messages_on_a_word_boundary(self) -> None:
        long_message = "palavra " * 80
        payload = {"items": [_item(message=long_message)]}
        content = insight_email_content(payload)
        _, message = content.items[0]
        assert len(message) <= 240
        assert message.endswith("...")
        assert "palavr..." not in message  # cut between words, not mid-word

    def test_collapses_whitespace(self) -> None:
        payload = {"items": [_item(title="Um\n  título", message="uma\t mensagem")]}
        content = insight_email_content(payload)
        assert content.items == [("Um título", "uma mensagem")]


class TestSuggestionExtraction:
    def test_opportunity_item_becomes_the_suggestion(self) -> None:
        payload = {
            "items": [
                _item(title="Delivery subiu"),
                _item(
                    item_type="oportunidade_economia",
                    title="Teto de delivery",
                    message="Definir um teto de R$ 480 devolve R$ 140 por mês.",
                ),
            ]
        }
        content = insight_email_content(payload)
        assert content.suggestion == "Definir um teto de R$ 480 devolve R$ 140 por mês."

    def test_suggestion_item_is_not_repeated_in_the_body(self) -> None:
        payload = {
            "items": [
                _item(title="Delivery subiu"),
                _item(item_type="oportunidade_economia", title="Teto de delivery"),
            ]
        }
        content = insight_email_content(payload)
        assert [title for title, _ in content.items] == ["Delivery subiu"]

    def test_only_the_first_actionable_item_is_promoted(self) -> None:
        payload = {
            "items": [
                _item(item_type="oportunidade_economia", message="Primeira sugestão."),
                _item(item_type="oportunidade_economia", message="Segunda sugestão."),
            ]
        }
        content = insight_email_content(payload)
        assert content.suggestion == "Primeira sugestão."
        assert len(content.items) == 1  # the second stays in the body

    def test_no_actionable_item_leaves_the_suggestion_empty(self) -> None:
        content = insight_email_content({"items": [_item()]})
        assert content.suggestion == ""
        assert len(content.items) == 1


class TestMalformedPayloads:
    def test_none_payload(self) -> None:
        content = insight_email_content(None)
        assert content.items == []
        assert content.suggestion == ""

    def test_payload_without_items(self) -> None:
        content = insight_email_content({"summary": "Resumo."})
        assert content.items == []

    def test_items_not_a_list(self) -> None:
        content = insight_email_content({"items": "nope"})
        assert content.items == []

    def test_non_dict_entries_are_skipped(self) -> None:
        content = insight_email_content({"items": ["nope", 42, None, _item()]})
        assert len(content.items) == 1

    def test_entries_missing_title_or_message_are_skipped(self) -> None:
        payload = {
            "items": [
                {"type": "gasto_elevado", "title": "Sem mensagem"},
                {"type": "gasto_elevado", "message": "Sem título"},
                {"type": "gasto_elevado", "title": "  ", "message": "  "},
                _item(title="Válido"),
            ]
        }
        content = insight_email_content(payload)
        assert [title for title, _ in content.items] == ["Válido"]

    def test_non_string_fields_are_skipped(self) -> None:
        payload = {"items": [{"type": "gasto_elevado", "title": 1, "message": 2}]}
        assert insight_email_content(payload).items == []

    def test_payload_not_a_mapping(self) -> None:
        assert insight_email_content(["nope"]).items == []  # type: ignore[arg-type]

    def test_item_without_type_still_renders_in_the_body(self) -> None:
        payload = {"items": [{"title": "Sem tipo", "message": "Mas tem conteúdo."}]}
        content = insight_email_content(payload)
        assert content.items == [("Sem tipo", "Mas tem conteúdo.")]
