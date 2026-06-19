from __future__ import annotations

from typing import cast

from app.docs.openapi_helpers import (
    OpenAPIDict,
    contract_header_param,
    deprecated_headers_doc,
    json_error_response,
    json_request_body,
    json_success_response,
)
from app.schemas.transaction_schema import TransactionSchema

TAG_TRANSACTIONS = "Transações"
ERROR_TOKEN_INVALIDO = "Token revogado"
ERROR_INTERNO = "Erro interno"
ERROR_TRANSACAO_NAO_ENCONTRADA = "Transação não encontrada"
ERROR_SEM_PERMISSAO = "Sem permissão"
ERROR_VALIDACAO = "Erro de validação"
DESC_NUMERO_PAGINA = "Número da página"
DESC_ITENS_POR_PAGINA = "Itens por página"
DESC_DATA_INICIAL = "Data inicial (YYYY-MM-DD)"
DESC_DATA_FINAL = "Data final (YYYY-MM-DD)"
CONTRACT_HEADER_PARAM = contract_header_param()

TRANSACTION_ID_PARAM = {
    "transaction_id": {
        "description": "ID da transação",
        "type": "string",
        "example": "cfef66a6-a148-49db-a72f-cc63b6080cf8",
    }
}

TRANSACTION_EXAMPLE = {
    "id": "cfef66a6-a148-49db-a72f-cc63b6080cf8",
    "title": "Conta de luz",
    "description": "Fatura mensal de energia",
    "observation": "Pagar antes do dia 10",
    "is_recurring": False,
    "is_installment": False,
    "installment_count": None,
    "amount": "150.00",
    "currency": "BRL",
    "source": "manual",
    "external_id": None,
    "bank_name": None,
    "status": "pending",
    "type": "expense",
    "due_date": "2026-03-10",
    "start_date": None,
    "end_date": None,
    "tag_id": "73c3b094-60bf-45d5-8e32-0f673b2ab4a2",
    "account_id": "2d16ea71-b7ae-4da7-adc4-e93e54cd52cb",
    "credit_card_id": None,
    "impact_policy": "full",
    "installment_group_id": None,
    "paid_at": None,
    "created_at": "2026-03-01T10:00:00+00:00",
    "updated_at": "2026-03-01T10:00:00+00:00",
}

TRANSACTION_CREATE_PAYLOAD_EXAMPLE = {
    "title": "Conta de luz",
    "description": "Fatura mensal de energia",
    "observation": "Pagar antes do dia 10",
    "amount": "150.00",
    "type": "expense",
    "status": "pending",
    "due_date": "2026-03-10",
    "tag_id": "73c3b094-60bf-45d5-8e32-0f673b2ab4a2",
    "account_id": "2d16ea71-b7ae-4da7-adc4-e93e54cd52cb",
    "impact_policy": "full",
}

TRANSACTION_LIST_META_EXAMPLE = {
    "pagination": {"total": 14, "page": 1, "per_page": 10, "pages": 2},
}

__all__ = [
    "OpenAPIDict",
    "cast",
    "contract_header_param",
    "deprecated_headers_doc",
    "json_error_response",
    "json_request_body",
    "json_success_response",
    "TransactionSchema",
    "TAG_TRANSACTIONS",
    "ERROR_TOKEN_INVALIDO",
    "ERROR_INTERNO",
    "ERROR_TRANSACAO_NAO_ENCONTRADA",
    "ERROR_SEM_PERMISSAO",
    "ERROR_VALIDACAO",
    "DESC_NUMERO_PAGINA",
    "DESC_ITENS_POR_PAGINA",
    "DESC_DATA_INICIAL",
    "DESC_DATA_FINAL",
    "CONTRACT_HEADER_PARAM",
    "TRANSACTION_ID_PARAM",
    "TRANSACTION_EXAMPLE",
    "TRANSACTION_CREATE_PAYLOAD_EXAMPLE",
    "TRANSACTION_LIST_META_EXAMPLE",
]
