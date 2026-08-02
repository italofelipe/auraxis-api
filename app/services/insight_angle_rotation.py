"""Editorial lens rotation for the daily AI insight.

Two daily readings built from an almost identical snapshot come out almost
identical — same prompt, same data, same opening. The fix is not in the cache
(``_get_cached_insight_for_snapshot`` already scopes by ``period_label``, so two
days never collide) but in the prompt: each day asks the model to go deep on a
different dimension.

The rotation is **deterministic**, not random. That buys three things random
would not:

* the same user on the same date always gets the same lens, so a test can pin it
  with freezegun and support can explain what happened;
* the choice is auditable — it is persisted in the insight metadata;
* preview/contract tests stay stable.

The per-user offset keeps two users from reading the same angle on the same day,
and ten lenses means the cycle does not line up with the week (7) or the month
(~30), so a given weekday never lands on the same lens twice in a row.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from uuid import UUID

__all__ = ["InsightAngle", "INSIGHT_ANGLES", "resolve_daily_angle"]


@dataclass(frozen=True)
class InsightAngle:
    """One editorial lens: an id for the metadata and a prompt instruction."""

    key: str
    instruction: str


INSIGHT_ANGLES: tuple[InsightAngle, ...] = (
    InsightAngle(
        key="pendencias_e_vencimentos",
        instruction=(
            "compromissos em aberto: o que vence nos próximos dias, o que já "
            "passou do prazo e quanto disso ainda cabe no que resta do mês"
        ),
    ),
    InsightAngle(
        key="categorias_e_tags",
        instruction=(
            "para onde o dinheiro está indo: concentração por categoria e por "
            "tag, o que subiu e o que caiu em relação ao mês anterior"
        ),
    ),
    InsightAngle(
        key="ritmo_e_burn_rate",
        instruction=(
            "o ritmo de saída: burn rate diário, quanto dele já foi consumido e "
            "onde o mês fecha se o ritmo atual continuar"
        ),
    ),
    InsightAngle(
        key="metas",
        instruction=(
            "as metas: distância até cada objetivo, quanto o ritmo atual antecipa "
            "ou atrasa a data prevista e qual delas merece atenção primeiro"
        ),
    ),
    InsightAngle(
        key="orcamentos",
        instruction=(
            "os orçamentos: folga restante por envelope, quais estão perto do "
            "limite e o que dá para remanejar sem apertar o resto"
        ),
    ),
    InsightAngle(
        key="cartoes",
        instruction=(
            "os cartões: faturas em aberto, quanto do limite está comprometido e "
            "como as compras parceladas pesam nos próximos meses"
        ),
    ),
    InsightAngle(
        key="carteira_e_alocacao",
        instruction=(
            "a carteira: composição atual, como ela se compara ao CDI e ao IPCA e "
            "se a alocação ainda combina com o perfil declarado"
        ),
    ),
    InsightAngle(
        key="projecao_e_cenarios",
        instruction=(
            "o horizonte: as projeções de 3, 6 e 12 meses, o que muda nelas se a "
            "sobra atual se mantiver e o que muda se ela cair pela metade"
        ),
    ),
    InsightAngle(
        key="habitos_e_recorrencia",
        instruction=(
            "os hábitos: o que se repete todo mês, quanto disso é assinatura ou "
            "recorrência e o que já não faz sentido manter"
        ),
    ),
    InsightAngle(
        key="comparativo_historico",
        instruction=(
            "a leitura histórica: como este mês se compara aos anteriores, quais "
            "extremos se destacam e o que a série diária revela sobre o padrão"
        ),
    ),
)


def _user_offset(user_id: UUID | str) -> int:
    """Stable per-user offset so two users read different angles on a given day.

    :param user_id: The user the insight belongs to.
    :returns: An integer offset derived from the id.
    """
    digest = hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def resolve_daily_angle(user_id: UUID | str, anchor: date) -> InsightAngle:
    """Pick the editorial lens for one user on one day.

    :param user_id: The user the insight belongs to.
    :param anchor: The day the insight covers.
    :returns: The lens to emphasise in the prompt.
    """
    index = (anchor.toordinal() + _user_offset(user_id)) % len(INSIGHT_ANGLES)
    return INSIGHT_ANGLES[index]
