from __future__ import annotations

from marshmallow import Schema, fields, validate


class AIInsightGenerateRequestSchema(Schema):
    period_type = fields.String(
        required=True,
        validate=validate.OneOf(["daily", "weekly", "monthly"]),
        metadata={
            "description": "Granularidade do insight financeiro.",
            "example": "daily",
        },
    )
    anchor_date = fields.Date(
        required=False,
        allow_none=True,
        metadata={
            "description": "Data âncora do período no formato YYYY-MM-DD.",
            "example": "2026-05-17",
        },
    )
    timezone = fields.String(
        required=False,
        allow_none=True,
        metadata={
            "description": (
                "Timezone IANA do usuário usado quando anchor_date é omitido. "
                "Também pode ser enviado no header X-Auraxis-Timezone."
            ),
            "example": "America/Sao_Paulo",
        },
    )
    preview_run_id = fields.UUID(
        required=False,
        allow_none=True,
        metadata={
            "description": (
                "Run de preview admin a ser reutilizado para manter o mesmo "
                "snapshot_hash na geração."
            ),
            "example": "550e8400-e29b-41d4-a716-446655440000",
        },
    )
    force_regenerate = fields.Boolean(
        required=False,
        load_default=False,
        metadata={
            "description": (
                "Quando true, regenera o insight mesmo que já exista um para o "
                "mesmo período (confirmação explícita do usuário). Sujeito à "
                "quota diária."
            ),
            "example": False,
        },
    )


class AIMonthlyReportRequestSchema(Schema):
    anchor_date = fields.Date(
        required=False,
        allow_none=True,
        metadata={
            "description": (
                "Data âncora do mês a consolidar. Quando omitida, a API usa a "
                "data atual."
            ),
            "example": "2026-05-21",
        },
    )
    enqueue = fields.Boolean(
        required=False,
        load_default=True,
        metadata={
            "description": (
                "Quando true, tenta enfileirar o processamento mensal em RQ. "
                "Ambientes sem Redis usam fallback síncrono."
            ),
            "example": True,
        },
    )


__all__ = ["AIInsightGenerateRequestSchema", "AIMonthlyReportRequestSchema"]
