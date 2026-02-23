# Coding Standards — auraxis-api

Última atualização: 2026-02-23

> Padrões canônicos de código Python para o `auraxis-api`. Agentes devem seguir este documento em toda entrega. Para governança de qualidade e CI, ver `.context/quality_gates.md`.

---

## 1. Formatação e estilo

### Black (formatador obrigatório)

```toml
# pyproject.toml
[tool.black]
line-length = 88
target-version = ["py311"]
```

- Nunca formatar manualmente — deixe o `black` decidir
- Rodar `black .` antes de todo commit
- CI: `black --check .` — zero diffs obrigatório

### isort (ordenação de imports)

```toml
# pyproject.toml
[tool.isort]
profile = "black"
line_length = 88
known_first_party = ["app", "config"]
```

Ordem de imports:
```python
# 1. stdlib
import os
import json
from typing import Optional, Any

# 2. third-party
from flask import Flask, jsonify
from sqlalchemy import Column, Integer, String
import marshmallow as ma

# 3. first-party (app/config)
from app.models.user import User
from config.settings import Settings
```

### Flake8

```ini
# .flake8 ou setup.cfg
max-line-length = 88
extend-ignore = E203, W503
```

- Zero warnings obrigatório
- E203 e W503 ignorados (compatibilidade com black)

---

## 2. Type annotations (obrigatório em todo código novo)

### mypy (strict mode)

```toml
# pyproject.toml
[tool.mypy]
python_version = "3.11"
strict = true
disallow_untyped_defs = true
warn_return_any = true
ignore_missing_imports = true
exclude = ["migrations", "tests"]
```

### Padrões de anotação

```python
# Funções — sempre anotar parâmetros e retorno
def get_user_by_id(user_id: int) -> Optional[User]:
    ...

# Retorno explícito de None
def soft_delete(resource_id: int) -> None:
    ...

# Usar tipos do typing para coleções
from typing import List, Dict, Optional, Any, Tuple

def list_transactions(
    user_id: int,
    filters: Dict[str, Any],
    limit: int = 20,
) -> List[Transaction]:
    ...

# Classes — anotar atributos de instância
class UserService:
    _repository: UserRepository
    _cache: Optional[Redis]

    def __init__(self, repository: UserRepository) -> None:
        self._repository = repository
        self._cache = None
```

### Evitar

```python
# ❌ Não usar Any desnecessariamente
def process(data: Any) -> Any: ...

# ✅ Preferir tipos concretos ou TypedDict
class UserPayload(TypedDict):
    email: str
    name: str
    role: str

def process(data: UserPayload) -> ProcessedUser: ...
```

---

## 3. Estrutura de diretórios

```
app/
  models/           # Entidades SQLAlchemy
  schemas/          # Marshmallow schemas (serialização/validação)
  application/
    services/       # Lógica de negócio (use cases)
  services/         # Domain services + integrações externas
  controllers/      # Adaptadores REST por domínio
  graphql/          # Schema, queries, mutations, security
  utils/            # Helpers transversais
  exceptions.py     # Exceções de domínio
config/             # Configurações por ambiente
tests/              # Suite de testes Pytest
migrations/         # Alembic migrations
docs/               # Runbooks, ADRs, segurança
```

---

## 4. Models (SQLAlchemy)

```python
from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship, Mapped, mapped_column
from app import db


class Transaction(db.Model):
    """Representa uma transação financeira do usuário."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    amount: Mapped[float] = mapped_column(nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User"] = relationship("User", back_populates="transactions")

    def __repr__(self) -> str:
        return f"<Transaction id={self.id} amount={self.amount}>"
```

Regras:
- Usar `Mapped` + `mapped_column` (SQLAlchemy 2.x style)
- `__tablename__` sempre explícito
- `__repr__` com informação útil para debug
- Soft delete via `is_deleted` — nunca deletar fisicamente sem justificativa
- Timestamps: `created_at`, `updated_at` onde aplicável

---

## 5. Schemas (Marshmallow)

```python
from marshmallow import Schema, fields, validate, validates, ValidationError
from typing import Any


class TransactionSchema(Schema):
    """Schema de serialização/validação para Transaction."""

    id = fields.Int(dump_only=True)
    user_id = fields.Int(required=True)
    amount = fields.Float(required=True, validate=validate.Range(min=0.01))
    description = fields.Str(validate=validate.Length(max=500), load_default=None)
    created_at = fields.DateTime(dump_only=True)

    @validates("amount")
    def validate_amount(self, value: float) -> None:
        if value <= 0:
            raise ValidationError("Amount must be positive.")


class TransactionCreateSchema(Schema):
    """Schema para criação — subconjunto de TransactionSchema."""

    amount = fields.Float(required=True, validate=validate.Range(min=0.01))
    description = fields.Str(validate=validate.Length(max=500), load_default=None)
```

Regras:
- Schema de entrada (`*CreateSchema`, `*UpdateSchema`) separado do schema de saída
- `dump_only=True` para campos gerados pelo sistema (`id`, `created_at`)
- Sempre validar entrada com `@validates` quando há regra de negócio
- Nunca retornar campos sensíveis (senha, tokens) no schema de saída

---

## 6. Services (lógica de negócio)

```python
from typing import Optional, List, Dict, Any
from app.models.transaction import Transaction
from app.schemas.transaction import TransactionSchema, TransactionCreateSchema
from app.exceptions import TransactionNotFoundError, InsufficientPermissionError


class TransactionService:
    """Orquestra casos de uso relacionados a transações."""

    _schema = TransactionSchema()
    _create_schema = TransactionCreateSchema()

    def get_by_id(self, transaction_id: int, user_id: int) -> Transaction:
        """Retorna transação ou lança TransactionNotFoundError."""
        transaction = Transaction.query.filter_by(
            id=transaction_id,
            is_deleted=False,
        ).first()
        if not transaction:
            raise TransactionNotFoundError(transaction_id)
        if transaction.user_id != user_id:
            raise InsufficientPermissionError()
        return transaction

    def create(self, payload: Dict[str, Any], user_id: int) -> Transaction:
        """Valida payload, cria e persiste uma transação."""
        data = self._create_schema.load(payload)
        transaction = Transaction(user_id=user_id, **data)
        db.session.add(transaction)
        db.session.commit()
        return transaction

    def list_for_user(
        self,
        user_id: int,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Transaction]:
        """Lista transações paginadas para um usuário."""
        return (
            Transaction.query
            .filter_by(user_id=user_id, is_deleted=False)
            .order_by(Transaction.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
```

Regras:
- Services não devem conhecer Flask, request, response — são agnósticos de framework
- Toda lógica de negócio fica no service, não no controller
- Levantar exceções de domínio (ver seção 9) — controllers tratam
- Um método = um caso de uso (responsabilidade única)

---

## 7. Controllers (REST)

```python
from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.application.services.transaction_service import TransactionService
from app.exceptions import TransactionNotFoundError, InsufficientPermissionError

transactions_bp = Blueprint("transactions", __name__, url_prefix="/transactions")
_service = TransactionService()


@transactions_bp.route("/", methods=["GET"])
@jwt_required()
def list_transactions() -> Response:
    user_id: int = get_jwt_identity()
    limit = request.args.get("limit", 20, type=int)
    offset = request.args.get("offset", 0, type=int)
    transactions = _service.list_for_user(user_id, limit=limit, offset=offset)
    return jsonify([t.to_dict() for t in transactions]), 200


@transactions_bp.route("/<int:transaction_id>", methods=["GET"])
@jwt_required()
def get_transaction(transaction_id: int) -> Response:
    user_id: int = get_jwt_identity()
    try:
        transaction = _service.get_by_id(transaction_id, user_id)
        return jsonify(transaction.to_dict()), 200
    except TransactionNotFoundError:
        return jsonify({"error": "Transaction not found"}), 404
    except InsufficientPermissionError:
        return jsonify({"error": "Forbidden"}), 403
```

Regras:
- Controllers são adaptadores — apenas traduzem HTTP → service → HTTP
- Nenhuma lógica de negócio no controller
- Sempre usar `@jwt_required()` em endpoints autenticados
- Tratar exceções de domínio aqui e mapear para status HTTP correto
- Retornar sempre JSON com `{"error": "mensagem"}` em erros

---

## 8. GraphQL (Ariadne)

```python
# app/graphql/mutations/transaction.py
from typing import Any, Dict
from ariadne import MutationType
from flask_jwt_extended import get_jwt_identity
from app.application.services.transaction_service import TransactionService
from app.exceptions import TransactionNotFoundError

mutation = MutationType()
_service = TransactionService()


@mutation.field("createTransaction")
def resolve_create_transaction(
    _: Any,
    info: Any,
    input: Dict[str, Any],
) -> Dict[str, Any]:
    user_id: int = get_jwt_identity()
    try:
        transaction = _service.create(input, user_id)
        return {"transaction": transaction, "errors": []}
    except Exception as e:
        return {"transaction": None, "errors": [str(e)]}
```

Regras:
- Resolvers são adaptadores — mesma lógica de controllers REST
- Sempre retornar `{"data": ..., "errors": []}` em mutations
- Nunca expor stack traces em respostas GraphQL em produção
- Schema GraphQL atualizado em `schema.graphql` quando campos mudam

---

## 9. Exceções de domínio

```python
# app/exceptions.py
class AuraxisBaseError(Exception):
    """Exceção base do domínio Auraxis."""

    def __init__(self, message: str = "An error occurred") -> None:
        self.message = message
        super().__init__(message)


class TransactionNotFoundError(AuraxisBaseError):
    def __init__(self, transaction_id: int) -> None:
        super().__init__(f"Transaction {transaction_id} not found.")


class InsufficientPermissionError(AuraxisBaseError):
    def __init__(self) -> None:
        super().__init__("You do not have permission to perform this action.")


class InvalidTokenError(AuraxisBaseError):
    def __init__(self) -> None:
        super().__init__("Invalid or expired token.")
```

Regras:
- Toda exceção de negócio herda de `AuraxisBaseError`
- Nomes descritivos com sufixo `Error`
- Controllers e resolvers capturam e mapeiam para resposta HTTP/GraphQL adequada
- **Nunca** deixar exceção não tratada subir para o usuário

---

## 10. Testes (Pytest)

### Estrutura

```
tests/
  conftest.py            # Fixtures compartilhadas
  unit/
    services/
      test_transaction_service.py
    models/
      test_transaction.py
  integration/
    rest/
      test_transaction_endpoints.py
    graphql/
      test_transaction_mutations.py
  contract/
    test_openapi_paridade.py
```

### O que testar (obrigatório por tipo)

| O que | Obrigatório? | Tipo de teste |
|:------|:-------------|:--------------|
| Services — happy path | ✅ Sim | Unit |
| Services — error paths (exceções) | ✅ Sim | Unit |
| Models — validações e constraints | ✅ Sim | Unit |
| REST endpoints — happy path | ✅ Sim | Integration |
| REST endpoints — auth guard | ✅ Sim | Integration |
| REST endpoints — 404/403/422 | ✅ Sim | Integration |
| GraphQL mutations | ✅ Sim | Integration |
| GraphQL queries | ✅ Sim | Integration |
| Schema Marshmallow — validações | ✅ Sim | Unit |
| OpenAPI paridade REST/GraphQL | ✅ Sim | Contract |

### Fixtures (conftest.py)

```python
import pytest
from typing import Generator
from app import create_app, db as _db
from app.models.user import User


@pytest.fixture(scope="session")
def app() -> Generator:
    """Cria app com banco em memória para a sessão de testes."""
    app = create_app("testing")
    with app.app_context():
        _db.create_all()
        yield app
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth_headers(client) -> dict:
    """Retorna headers JWT de um usuário de teste."""
    # ... login e retorno do token
    return {"Authorization": f"Bearer {token}"}
```

### Exemplo de teste unitário (service)

```python
from unittest.mock import MagicMock, patch
from app.application.services.transaction_service import TransactionService
from app.exceptions import TransactionNotFoundError
import pytest


class TestTransactionService:
    def setup_method(self) -> None:
        self.service = TransactionService()

    def test_get_by_id_not_found_raises(self) -> None:
        with patch(
            "app.application.services.transaction_service.Transaction.query"
        ) as mock_query:
            mock_query.filter_by.return_value.first.return_value = None
            with pytest.raises(TransactionNotFoundError):
                self.service.get_by_id(999, user_id=1)

    def test_list_for_user_returns_paginated(self) -> None:
        with patch(
            "app.application.services.transaction_service.Transaction.query"
        ) as mock_query:
            mock_transactions = [MagicMock(), MagicMock()]
            (
                mock_query.filter_by.return_value
                .order_by.return_value
                .limit.return_value
                .offset.return_value
                .all.return_value
            ) = mock_transactions
            result = self.service.list_for_user(user_id=1, limit=10)
            assert len(result) == 2
```

### Exemplo de teste de integração (REST)

```python
def test_get_transaction_unauthorized(client) -> None:
    resp = client.get("/transactions/1")
    assert resp.status_code == 401


def test_get_transaction_not_found(client, auth_headers) -> None:
    resp = client.get("/transactions/99999", headers=auth_headers)
    assert resp.status_code == 404
    data = resp.get_json()
    assert "error" in data


def test_create_transaction_success(client, auth_headers) -> None:
    payload = {"amount": 150.0, "description": "Groceries"}
    resp = client.post("/transactions/", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["amount"] == 150.0
```

### Coverage e thresholds

```bash
# Coverage completo
pytest -m "not schemathesis" --cov=app --cov-report=term-missing --cov-fail-under=85

# Módulos críticos — aspirar a cobertura mais alta
# app/application/services/ → ≥ 90%
# app/models/ → ≥ 85%
# app/controllers/ → ≥ 85%
```

---

## 11. Segurança

### O que nunca fazer

```python
# ❌ NUNCA hardcodar secrets
SECRET_KEY = "my-secret-key-123"
DATABASE_URL = "postgresql://user:pass@host/db"

# ✅ SEMPRE via environment
import os
SECRET_KEY = os.environ["SECRET_KEY"]
DATABASE_URL = os.environ["DATABASE_URL"]
```

### Validação de entrada

```python
# ✅ Sempre validar via Marshmallow antes de processar
schema = TransactionCreateSchema()
try:
    data = schema.load(request.json)
except ValidationError as err:
    return jsonify({"errors": err.messages}), 422
```

### Bandit

Configurado para bloquear em HIGH severity:
```bash
bandit -r app -lll -iii
```

Problemas comuns detectados pelo Bandit:
- `subprocess.call` com `shell=True` → usar lista de argumentos
- `hashlib.md5()` → usar `hashlib.sha256()` ou bcrypt para senhas
- SQL injection potencial → sempre usar ORM/parâmetros

### Autenticação

- Todos os endpoints autenticados usam `@jwt_required()`
- `get_jwt_identity()` retorna apenas o `user_id` (nunca o objeto completo)
- Tokens de reset de senha: hash + expiração + uso único
- Reset de senha revoga sessão ativa (`current_jti`)

---

## 12. Migrations (Alembic)

```bash
# Criar migration após mudar um model
flask db migrate -m "add investor_profile table"

# Aplicar migrations
flask db upgrade

# Ver histórico
flask db history
```

Regras:
- **Nunca** editar migrations geradas — criar nova se necessário
- **Nunca** referenciar dados hardcoded em migrations
- Migrations com operações destrutivas: sempre criar script de rollback
- Naming: mensagem descritiva no `-m` (ex: `add amount_currency to transactions`)

---

## 13. Documentação inline

```python
def reset_password(
    token: str,
    new_password: str,
    confirm_password: str,
) -> User:
    """
    Valida o token de reset e atualiza a senha do usuário.

    Args:
        token: Token de reset recebido por e-mail (raw, não hash).
        new_password: Nova senha em plain text.
        confirm_password: Confirmação da nova senha.

    Returns:
        User: Objeto User com senha atualizada.

    Raises:
        InvalidTokenError: Token inválido, expirado ou já usado.
        ValidationError: Senhas não conferem.
    """
    ...
```

Regras:
- Docstrings obrigatórias em:
  - Todos os métodos públicos de services
  - Todos os endpoints de controller
  - Todos os resolvers GraphQL
  - Todos os models (docstring de classe)
- Formato: Google style (Args, Returns, Raises)
- Funções simples/privadas: docstring opcional, mas nome deve ser autoexplicativo

---

## 14. Performance e banco de dados

```python
# ✅ Usar select_in loading para relacionamentos conhecidos
transactions = Transaction.query.options(
    selectinload(Transaction.category)
).filter_by(user_id=user_id).all()

# ❌ Evitar N+1 queries
for t in transactions:
    print(t.category.name)  # N+1 se category não foi prefetched
```

Regras:
- Evitar N+1: sempre usar `selectinload`, `joinedload` ou `subqueryload`
- Paginação obrigatória em todas as listagens (`limit` + `offset`)
- Indexes: criar migration de index se query frequente em campo não indexado
- Transações: usar `db.session` explicitamente para operações atômicas

---

## 15. Referências

- `.context/04_architecture_snapshot.md` — snapshot de arquitetura detalhado
- `.context/quality_gates.md` — quality gates e CI completo
- `steering.md` — governança de execução e branching
- `auraxis-platform/.context/25_quality_security_playbook.md` — playbook unificado de plataforma
- `auraxis-platform/.context/08_agent_contract.md` — contrato de comportamento de agentes
- `docs/RUNBOOK.md` — operações e recuperação
