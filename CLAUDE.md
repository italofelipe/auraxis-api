# CLAUDE.md — Auraxis Operational Directive for Claude

## Identity

You are an AI software engineer working on **auraxis-api** — the Auraxis backend
service, a personal financial management platform built with Flask, SQLAlchemy,
Marshmallow, GraphQL (Graphene 3), and PostgreSQL.

## Session Bootstrap (MANDATORY — execute in order)

Before starting any work, read these files in sequence:

1. `.context/README.md` — bootstrap overview and conventions
2. `.context/01_sources_of_truth.md` — document authority hierarchy
3. `.context/04_architecture_snapshot.md` — codebase structure
4. `steering.md` — execution governance, branching, quality gates
5. `product.md` — product vision and functional scope
6. **GitHub Projects** — backlog and task status (do NOT read `TASKS.md`; it is a deprecated tombstone)
7. `.context/05_quality_and_gates.md` — quality gates and Definition of Done

If resuming a session, also check `.context/handoffs/` for pending handoffs.

## Source of Truth Hierarchy

When documents conflict, follow this priority order:

1. **GitHub Projects** — status, priority, progress tracking (canonical source of truth)
2. **product.md** — product intent, scope, business direction
3. **steering.md** — execution governance, branching, quality gates
4. **.context/** — operational workflows and architecture reference
5. **docs/** — runbooks, ADRs, security, CI/CD

## Operational Boundaries

### You MUST do autonomously (no human approval needed)

- Read any file in the repository
- Run quality gates: `ruff format`, `ruff check`, `mypy`, `pytest`
- Create branches following conventional branching (`feat/`, `fix/`, `refactor/`, etc.)
- Write code in: `app/`, `tests/`, `migrations/`, `scripts/`, `docs/`
- Run existing test suites
- Update GitHub Projects status when work is complete (via `gh issue close` or PR with `Closes #N`)
- Create handoff documents in `.context/handoffs/`

### You MUST ask before proceeding

- Product/business decisions (scope changes, UX, pricing)
- Architecture changes with cross-cutting impact
- Deleting existing code or tests
- Changes to: `steering.md`, `product.md`, `.context/01-07` files
- AWS/infrastructure operations
- Database schema changes that affect existing data
- Deploy to any environment

### You MUST NEVER do

- Write to `.env`, `.env.dev`, `.env.prod`
- Commit secrets, keys, tokens, or credentials
- Modify `run.py`, `Dockerfile*`, `docker-compose*`, `pyproject.toml` without explicit human approval
- Push directly to `master`
- Use `git add .` (always use selective file staging)
- Skip quality gates before committing

## Feature Delivery Cycle

The full operational cycle is defined in `.context/07_operational_cycle.md`.
Summary:

1. **SPEC** — PO gives natural language briefing → Agent creates feature card.
2. **ANALYSIS** — Agent reads codebase, identifies risks/gaps/opportunities.
3. **REFINEMENT** — PO + Agent align on tasks breakdown and validation.
4. **EXECUTION** — Agent implements autonomously (code, tests, commits).
5. **DELIVERY** — Agent writes delivery report with feedback and debt.
6. **CLOSE** — PO reviews, accepts, signals next feature.

Templates:
- Feature card: `.context/templates/feature_card_template.md`
- Feature spec (detailed): `.context/templates/feature_spec_template.md`
- Delivery report: `.context/templates/delivery_report_template.md`
- Handoff: `.context/templates/handoff_template.md`

## Multi-Agent Collaboration

| Agent | Role | Status |
| :--- | :--- | :--- |
| **Claude** | Primary executor: implementation, review, analysis | Default |
| **GPT** | Consultive: alternate analysis | On-demand only |
| **Gemini** | Consultive: architecture second opinions | On-demand only |
| **CrewAI** | Automated pipeline | Paused indefinitely |

Execution model: Claude works **locally** (CLI, IDE). Previous label-triggered
workflows (`agent-implement.yml`, `agent-qa.yml`, `agent-watchdog*.yml`) were
retired on 2026-05-27 — see platform ADR `agent_workflows_decommissioned.md`.

All agents share:
- Knowledge base: `.context/`
- Task tracking: **GitHub Projects** (canonical)
- Handoffs: `.context/handoffs/`
- Delivery reports: `.context/reports/`
- Quality gates: `.context/05_quality_and_gates.md`
- Feature card format: `.context/templates/feature_card_template.md`

**Handoff interop:** Any agent can read and write handoffs in `.context/handoffs/`
that other agents consume. Use `templates/handoff_template.md` for consistency.

## Quality Gates (run before every commit)

**Canonical CI-parity command** (mirrors GitHub Actions ci.yml exactly):
```bash
bash scripts/run_ci_quality_local.sh --local
```

This runs in order: check_feature_flags → repo_hygiene → graphql_auth_config →
alembic_single_head → security_exception_governance → pip_audit → ruff format →
ruff check → mypy → bandit → **contracts snapshot** → pytest (cov ≥ 85%).

**Contract snapshots are locked (#1536).** `openapi.json`, `schema.graphql`,
`graphql.introspection.json` and `graphql.operations.manifest.json` are
versionados e conferidos contra o código a cada PR pelo job
`Contracts (OpenAPI + GraphQL snapshot)`. Mudou controller, schema ou resolver?
Regenere e commite o snapshot na mesma PR:

```bash
npm run contracts:check                                   # detecta o drift
flask openapi-export --output openapi.json                # corrige o REST
python3 scripts/export_graphql_docs.py --source runtime    # corrige o GraphQL
```

**Individual checks** (when debugging a specific gate):
```bash
bash scripts/bootstrap_local_env.sh
scripts/python_tool.sh ruff format .
scripts/python_tool.sh ruff check app tests config run.py run_without_db.py
scripts/python_tool.sh mypy app
scripts/repo_bin.sh pytest -m "not schemathesis" --cov=app --cov-fail-under=85
```

## Branching and Commits

- **Branch format:** `type/scope-short-description`
- **Valid types:** `feat`, `fix`, `refactor`, `chore`, `docs`, `test`, `perf`, `security`
- **Commits:** Conventional Commits format, one responsibility per commit
- **Never** commit directly to `master`
- **Always** use small, granular commits for safe rollback

## Definition of Done

- Feature implemented with adequate tests
- No REST/GraphQL contract regression
- All linters, type-check, and tests passing
- Documentation and traceability updated (affected docs, GitHub Projects card updated to Done)
- Branch pushed with granular commits and clear messages
- Technical debt registered when applicable

## Project Tech Stack

| Layer | Technology |
| :--- | :--- |
| Backend | Python 3.13, Flask |
| ORM | SQLAlchemy with Flask-SQLAlchemy |
| Serialization | Marshmallow Schemas |
| API | GraphQL (Graphene 3) + REST (Flask controllers) |
| Migrations | Alembic via Flask-Migrate |
| Tests | Pytest (85% coverage minimum) |
| Database | PostgreSQL |
| Cache | Redis |
| Deploy | AWS EC2 + Docker Compose + Nginx |
| Code Quality | Ruff, mypy, Bandit, Gitleaks |

## Key Directories

| Directory | Purpose |
| :--- | :--- |
| `app/models/` | SQLAlchemy entity definitions |
| `app/schemas/` | Marshmallow serialization/validation schemas |
| `app/application/services/` | Business logic and use case orchestration |
| `app/services/` | Domain services and integrations (e.g., BRAPI) |
| `app/controllers/` | REST adapter layer per domain |
| `app/graphql/` | GraphQL schema, queries, mutations, security |
| `tests/` | Pytest test suite |
| `migrations/` | Alembic database migrations |
| `.context/` | AI knowledge base (SDD + agentic workflows) |
| `docs/` | Runbooks, ADRs, security docs |

## Migration Conventions (PostgreSQL)

> Origem: post-mortem PR #1174. Violações causam falhas silenciosas em SQLite e explosões no CI PostgreSQL.

### Enums — usar `native_enum=False` por padrão

```python
# ✅ Correto — VARCHAR + CHECK constraint, sem CREATE TYPE, sem risco de idempotência
transport = db.Column(
    db.Enum(PushTransport, name="push_transport", native_enum=False),
    nullable=False
)

# ⚠️  Só usar native_enum=True se houver razão explícita (ex: performance de JOIN)
#     + migration testada com scripts/test_migrations_local.sh
```

**Por quê:** `native_enum=True` (default SQLAlchemy) registra DDL listener na metadata.
Quando `flask db upgrade` executa e Alembic chama `context.configure(target_metadata=...)`,
esse listener emite `CREATE TYPE` **antes** da migration rodar. A migration tenta criar o mesmo
tipo → `ERROR: type already exists` → bootstrap do CI falha em loop.

### Antes de fazer push com nova migration

```bash
bash scripts/test_migrations_local.sh   # sobe postgres:16 efêmero, aplica up + down
```

O pre-commit hook `migration-pattern-check` também bloqueia padrões proibidos:

| Padrão detectado | Alternativa |
|---|---|
| `op.execute("CREATE TYPE ...")` sem verificação | `native_enum=False` ou check em `pg_type` |
| `op.get_bind()` | `op.get_context().connection` |
| `ENUM(...).create(op.get_bind())` | `native_enum=False` |
| `server_default=gen_random_uuid()` | `default=uuid.uuid4` no modelo |

### Endpoints com validação customizada Marshmallow

Ao criar endpoint com `@validates_schema` ou validação condicional por tipo,
adicionar ENRICHMENT em `scripts/openapi_to_postman.py` **na mesma PR**:

```python
"POST /meu/endpoint": {
    "test_lines": [
        "pm.test('Meu endpoint — expected 200 or 400', function () {",
        "  pm.expect(pm.response.code).to.be.oneOf([200, 400]);",
        "});",
    ],
},
```

Sem ENRICHMENT, o Newman smoke test vai falhar porque o body auto-gerado pelo schema
não passa na validação customizada.

## GraphQL Architecture Decisions

Key ADRs governing the GraphQL layer:

- [`docs/adr/0002-graphql-ownership.md`](docs/adr/0002-graphql-ownership.md) — REST vs GraphQL ownership boundaries; when to use each protocol
- [`docs/adr/0003-graphql-flat-types-no-dataloader.md`](docs/adr/0003-graphql-flat-types-no-dataloader.md) — flat Graphene types, service-layer batching, no DataLoader
- [`docs/adr/0004-graphql-ownership-scope-completion.md`](docs/adr/0004-graphql-ownership-scope-completion.md) — extends ADR-0002 to Subscription mutations; documents ticker exception

## Mapa de dominios disponíveis

Use esta tabela antes de criar qualquer novo controller, service ou model.
**Verifique primeiro se o dominio ja existe — evite duplicar logica.**

| Dominio | Controllers | Services principais | Models |
|---------|-------------|---------------------|--------|
| auth | `auth_controller` | `auth_security_policy_service`, `login_identity_service`, `session_service`, `email_confirmation_service`, `password_reset_service`, `password_verification_service` | `User`, `RefreshToken` |
| transactions | `transaction_controller` | `transaction_application_service`, `transaction_ledger_service`, `transaction_query_service`, `transaction_reminder_service` | `Transaction`, `Tag`, `SharedEntry` |
| goals | `goal_controller` | `goal_application_service` | `Goal` |
| wallet | `wallet_controller` | `wallet_application_service`, `investment_application_service` | `WalletEntry`, `UserTicker`, `InvestmentOperation` |
| budget | `budget/` (subpkg) | — | `BudgetEnvelope` |
| simulation | `simulation_controller` | `simulation_application_service`, `installment_vs_cash_application_service`, `installment_vs_cash_bridge_service` | `Simulation` |
| subscription | `subscription_controller` | `entitlement_application_service`, `billing_email_service` | `Subscription`, `Entitlement` |
| alerts | `alert_controller` | — | `Alert` |
| user | `user_controller` | `user_profile_service`, `authenticated_user_context_service`, `authenticated_user_bootstrap_service` | `User`, `Account` |
| advisory | — | `advisory_service` | — |
| fiscal | `fiscal/` (subpkg) | — | `Fiscal` |
| credit_card | `credit_card/` (subpkg) | — | `CreditCard` |
| dashboard | `dashboard/` (subpkg) | — | — |
| observability | `observability_controller` | — | `AuditEvent`, `WebhookEvent` |

**Antes de criar um novo service**: consulte `app/application/services/CLAUDE.md`.
**Antes de criar um novo controller**: consulte `app/controllers/CLAUDE.md`.
