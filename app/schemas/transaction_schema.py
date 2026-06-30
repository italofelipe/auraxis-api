from marshmallow import Schema, fields, pre_load, validate

from app.schemas.sanitization import sanitize_string_fields


class TransactionSchema(Schema):
    """Schema para criação e atualização de transações financeiras"""

    class Meta:
        name = "TransactionCreate"

    id = fields.UUID(
        dump_only=True,
        metadata={"description": "ID único da transação (gerado automaticamente)"},
    )
    user_id = fields.UUID(
        dump_only=True,
        metadata={"description": "ID do usuário proprietário da transação"},
    )
    title = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=120),
        metadata={
            "description": "Título da transação",
            "example": "Pagamento da conta de luz",
        },
    )
    description = fields.Str(
        allow_none=True,
        load_default=None,
        validate=validate.Length(max=300),
        metadata={
            "description": "Descrição detalhada da transação",
            "example": "Conta de energia elétrica do mês de janeiro",
        },
    )
    observation = fields.Str(
        allow_none=True,
        load_default=None,
        validate=validate.Length(max=500),
        metadata={
            "description": "Observações adicionais sobre a transação",
            "example": "Pagar até o dia 10 para evitar multa",
        },
    )
    is_recurring = fields.Bool(
        metadata={"description": "Indica se a transação é recorrente", "example": False}
    )
    is_installment = fields.Bool(
        metadata={"description": "Indica se a transação é parcelada", "example": False}
    )
    installment_count = fields.Int(
        validate=validate.Range(min=1, max=60),
        metadata={
            "description": "Número de parcelas (apenas se is_installment=True)",
            "example": 12,
        },
    )
    recurrence_interval = fields.Int(
        load_default=1,
        validate=validate.Range(min=1, max=365),
        metadata={
            "description": "Intervalo da recorrência (a cada N unidades)",
            "example": 1,
        },
    )
    recurrence_unit = fields.Str(
        load_default="month",
        validate=validate.OneOf(["day", "week", "month", "year"]),
        metadata={
            "description": "Unidade da recorrência: day, week, month ou year",
            "example": "month",
        },
    )
    amount = fields.Decimal(
        as_string=True,
        required=True,
        validate=validate.Range(min=0.01),
        metadata={"description": "Valor da transação", "example": "150.50"},
    )
    currency = fields.Str(
        validate=validate.Length(equal=3),
        metadata={"description": "Código da moeda (ISO 4217)", "example": "BRL"},
    )
    status = fields.Str(
        validate=validate.OneOf(
            ["paid", "pending", "cancelled", "postponed", "overdue"]
        ),
        metadata={"description": "Status atual da transação", "example": "pending"},
    )
    type = fields.Str(
        required=True,
        validate=validate.OneOf(["income", "expense"]),
        metadata={
            "description": "Tipo da transação: receita ou despesa",
            "example": "expense",
        },
    )
    due_date = fields.Date(
        required=True,
        metadata={
            "description": "Data de vencimento da transação",
            "example": "2024-02-15",
        },
    )
    start_date = fields.Date(
        allow_none=True,
        load_default=None,
        metadata={
            "description": "Data de início (para transações recorrentes)",
            "example": "2024-01-01",
        },
    )
    end_date = fields.Date(
        allow_none=True,
        load_default=None,
        metadata={
            "description": "Data de fim (para transações recorrentes)",
            "example": "2024-12-31",
        },
    )
    category = fields.Str(
        allow_none=True,
        load_default=None,
        validate=validate.OneOf(
            [
                "alimentacao",
                "transporte",
                "moradia",
                "saude",
                "lazer",
                "educacao",
                "investimentos",
                "poupanca",
                "outros",
            ]
        ),
        metadata={"description": "Categoria estruturada para controle de orçamento"},
    )
    tag_id = fields.UUID(
        allow_none=True,
        metadata={"description": "ID da tag associada à transação"},
    )
    account_id = fields.UUID(
        allow_none=True,
        metadata={"description": "ID da conta bancária associada"},
    )
    credit_card_id = fields.UUID(
        allow_none=True,
        metadata={"description": "ID do cartão de crédito associado"},
    )
    impact_policy = fields.Str(
        load_default="full",
        validate=validate.OneOf(["full", "cards_only", "planned_until_bill"]),
        metadata={
            "description": (
                "Política de impacto do lançamento: full reflete em todas as áreas; "
                "cards_only fica restrito a cartões/fatura; planned_until_bill "
                "mantém o lançamento para planejamento da fatura."
            ),
            "example": "full",
        },
    )
    auto_settle = fields.Bool(
        load_default=False,
        metadata={
            "description": (
                "Quando true, a transação é marcada automaticamente como paga/recebida "
                "no vencimento pelo job diário de auto-settle (opt-in, padrão false)."
            ),
            "example": False,
        },
    )
    installment_group_id = fields.UUID(
        dump_only=True,
        metadata={"description": "ID do grupo de parcelas (gerado automaticamente)"},
    )
    paid_at = fields.DateTime(
        allow_none=True,
        metadata={
            "description": "Data e hora do pagamento",
            "example": "2024-02-10T14:30:00Z",
        },
    )
    created_at = fields.DateTime(
        dump_only=True,
        metadata={"description": "Data de criação da transação"},
    )
    updated_at = fields.DateTime(
        dump_only=True,
        metadata={"description": "Data da última atualização"},
    )

    @pre_load
    def sanitize_input(self, data: object, **kwargs: object) -> object:
        sanitized = sanitize_string_fields(
            data,
            {
                "title",
                "description",
                "observation",
                "type",
                "status",
                "currency",
                "impact_policy",
            },
        )
        if isinstance(sanitized, dict):
            if isinstance(sanitized.get("type"), str):
                sanitized["type"] = str(sanitized["type"]).lower()
            if isinstance(sanitized.get("status"), str):
                sanitized["status"] = str(sanitized["status"]).lower()
            if isinstance(sanitized.get("currency"), str):
                sanitized["currency"] = str(sanitized["currency"]).upper()
            if isinstance(sanitized.get("impact_policy"), str):
                sanitized["impact_policy"] = str(sanitized["impact_policy"]).lower()
        return sanitized


class TransactionResponseSchema(Schema):
    """Schema para resposta de transações"""

    class Meta:
        name = "TransactionResponse"

    id = fields.UUID(metadata={"description": "ID único da transação"})
    title = fields.Str(metadata={"description": "Título da transação"})
    description = fields.Str(
        allow_none=True,
        metadata={"description": "Descrição da transação"},
    )
    observation = fields.Str(allow_none=True, metadata={"description": "Observações"})
    is_recurring = fields.Bool(metadata={"description": "Se é recorrente"})
    is_installment = fields.Bool(metadata={"description": "Se é parcelada"})
    installment_count = fields.Int(
        allow_none=True,
        metadata={"description": "Número de parcelas"},
    )
    amount = fields.Decimal(
        as_string=True, metadata={"description": "Valor da transação"}
    )
    currency = fields.Str(metadata={"description": "Moeda"})
    source = fields.Str(metadata={"description": "Origem da transação"})
    external_id = fields.Str(
        allow_none=True,
        metadata={"description": "Identificador externo da origem da transação"},
    )
    bank_name = fields.Str(
        allow_none=True,
        metadata={"description": "Banco associado à origem importada"},
    )
    status = fields.Str(metadata={"description": "Status da transação"})
    type = fields.Str(metadata={"description": "Tipo da transação"})
    due_date = fields.Date(metadata={"description": "Data de vencimento"})
    start_date = fields.Date(
        allow_none=True,
        metadata={"description": "Data de início"},
    )
    end_date = fields.Date(
        allow_none=True,
        metadata={"description": "Data de fim"},
    )
    tag_id = fields.UUID(allow_none=True, metadata={"description": "ID da tag"})
    account_id = fields.UUID(allow_none=True, metadata={"description": "ID da conta"})
    credit_card_id = fields.UUID(
        allow_none=True,
        metadata={"description": "ID do cartão de crédito"},
    )
    impact_policy = fields.Str(
        metadata={"description": "Política de impacto do lançamento"}
    )
    auto_settle = fields.Bool(
        metadata={"description": "Se marca automaticamente como paga no vencimento"}
    )
    installment_group_id = fields.UUID(
        allow_none=True, metadata={"description": "ID do grupo de parcelas"}
    )
    paid_at = fields.DateTime(
        allow_none=True,
        metadata={"description": "Data do pagamento"},
    )
    created_at = fields.DateTime(
        allow_none=True,
        metadata={"description": "Data de criação"},
    )
    updated_at = fields.DateTime(
        allow_none=True,
        metadata={"description": "Data de atualização"},
    )


class TransactionListSchema(Schema):
    """Schema para listagem de transações"""

    class Meta:
        name = "TransactionList"

    transactions = fields.List(fields.Nested(TransactionResponseSchema))
    total = fields.Int(metadata={"description": "Total de transações"})
    page = fields.Int(metadata={"description": "Página atual"})
    per_page = fields.Int(metadata={"description": "Itens por página"})


class MonthlySummarySchema(Schema):
    """Schema para resumo mensal de transações"""

    class Meta:
        name = "MonthlySummary"

    income_total = fields.Str(metadata={"description": "Total de receitas do mês"})
    expense_total = fields.Str(metadata={"description": "Total de despesas do mês"})
    transactions = fields.List(fields.Nested(TransactionResponseSchema))
