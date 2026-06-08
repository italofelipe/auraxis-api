from marshmallow import Schema, fields, validate

CREDIT_CARD_BRANDS = ("visa", "mastercard", "elo", "hipercard", "amex", "other")

BENEFITS_MAX_ITEMS = 12
BENEFITS_MAX_ITEM_LENGTH = 120


class CreditCardSchema(Schema):
    """Schema para criação e atualização de cartões de crédito"""

    id = fields.UUID(
        dump_only=True,
        metadata={"description": "ID único do cartão (gerado automaticamente)"},
    )
    user_id = fields.UUID(
        required=False,
        metadata={"description": "ID do usuário proprietário do cartão"},
    )
    name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=100),
        metadata={
            "description": "Nome do cartão de crédito",
            "example": "Nubank Mastercard",
        },
    )
    brand = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.OneOf(CREDIT_CARD_BRANDS),
        metadata={
            "description": "Bandeira do cartão",
            "example": "mastercard",
        },
    )
    limit_amount = fields.Decimal(
        required=False,
        allow_none=True,
        as_string=False,
        metadata={
            "description": "Limite do cartão",
            "example": 5000.00,
        },
    )
    closing_day = fields.Int(
        required=False,
        allow_none=True,
        validate=validate.Range(min=1, max=31),
        metadata={
            "description": "Dia de fechamento da fatura (1-31)",
            "example": 20,
        },
    )
    due_day = fields.Int(
        required=False,
        allow_none=True,
        validate=validate.Range(min=1, max=31),
        metadata={
            "description": "Dia de vencimento da fatura (1-31)",
            "example": 5,
        },
    )
    bank = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(max=80),
        metadata={
            "description": "Nome do banco emissor",
            "example": "Nubank",
        },
    )
    description = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(max=300),
        metadata={
            "description": "Descrição livre do cartão",
            "example": "Cartão principal de despesas mensais",
        },
    )
    benefits = fields.List(
        fields.Str(validate=validate.Length(max=BENEFITS_MAX_ITEM_LENGTH)),
        required=False,
        allow_none=True,
        validate=validate.Length(max=BENEFITS_MAX_ITEMS),
        metadata={
            "description": "Lista de benefícios do cartão (máx 12 itens × 120 chars)",
            "example": ["Cashback 1%", "Sala VIP em aeroportos"],
        },
    )


class CreditCardResponseSchema(Schema):
    """Schema para resposta de cartões de crédito"""

    id = fields.UUID(metadata={"description": "ID único do cartão"})
    user_id = fields.UUID(metadata={"description": "ID do usuário"})
    name = fields.Str(metadata={"description": "Nome do cartão"})
    brand = fields.Str(allow_none=True, metadata={"description": "Bandeira do cartão"})
    limit_amount = fields.Float(
        allow_none=True, metadata={"description": "Limite do cartão"}
    )
    closing_day = fields.Int(
        allow_none=True, metadata={"description": "Dia de fechamento"}
    )
    due_day = fields.Int(allow_none=True, metadata={"description": "Dia de vencimento"})
    bank = fields.Str(allow_none=True, metadata={"description": "Banco emissor"})
    description = fields.Str(
        allow_none=True, metadata={"description": "Descrição livre"}
    )
    benefits = fields.List(
        fields.Str(),
        allow_none=True,
        metadata={"description": "Lista de benefícios"},
    )
    created_at = fields.DateTime(
        allow_none=True,
        format="iso",
        metadata={"description": "Data de criação do registro"},
    )
    updated_at = fields.DateTime(
        allow_none=True,
        format="iso",
        metadata={"description": "Data da última atualização"},
    )


class CreditCardListSchema(Schema):
    """Schema para listagem de cartões de crédito"""

    credit_cards = fields.List(fields.Nested(CreditCardResponseSchema))
    total = fields.Int(metadata={"description": "Total de cartões"})
    page = fields.Int(metadata={"description": "Página atual"})
    per_page = fields.Int(metadata={"description": "Itens por página"})
