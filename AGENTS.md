# AGENTS.md — auraxis-api

> Lido por Codex, Claude Code e qualquer agente de IA.
> Para Claude Code, o arquivo canônico é `CLAUDE.md` — este é o espelho para outros agentes.

## Identidade do repositório

Backend do Auraxis · Python 3.13 · Flask · SQLAlchemy · GraphQL (Graphene 3) · PostgreSQL (RDS)

## Passo 1 — Verificar coordenação antes de começar

```bash
# Ver quem está trabalhando no quê agora
cat /caminho/para/auraxis-platform/.context/active_agents.json

# Ver issues In Progress no GitHub Projects (não pegar issues já reclamadas)
gh issue list --label "agent:in-progress" --state open
```

**Só comece se a issue estiver em "Todo" e não houver outro agente nela.**

## Passo 2 — Registrar seu trabalho

Antes de escrever qualquer código, atualize `.context/active_agents.json` na platform com:
- `agent`: seu nome/id (ex: "codex", "claude")
- `issue`: número da issue
- `repo`: "auraxis-api"
- `branch`: nome do branch que vai criar

## Setup do ambiente

```bash
source .venv/bin/activate
# Quality gate (rodar antes de todo commit):
bash scripts/run_ci_quality_local.sh --local
```

## Convenção de branch

```
feat/claude-<desc>    feat/codex-<desc>
fix/claude-<desc>     fix/codex-<desc>
refactor/claude-<desc>
```

## Regras críticas — NÃO VIOLAR

- ❌ `git add .` ou `git add -A` → sempre stage seletivo por arquivo
- ❌ commit direto em `master` → sempre branch + PR
- ❌ `--no-verify` em commits → os hooks existem por razão
- ❌ prefixar commits, PRs ou títulos de alterações com `[codex]`; use o escopo funcional (`feat:`, `fix:` etc.)
- ❌ escrever em `.env*` (exceto `.env.example`)
- ❌ `native_enum=True` em migrations → usar `native_enum=False` (quebra CI PostgreSQL)
- ❌ `op.get_bind()` em migrations → usar `op.get_context().connection`
- ❌ `gen_random_uuid()` como server_default → usar `default=uuid.uuid4` no modelo

## Quality gate obrigatório

```bash
bash scripts/run_ci_quality_local.sh --local
# Cobre: feature_flags → repo_hygiene → ruff format → ruff check → mypy → bandit → pytest (≥85%)
```

## Migrations — validar antes de commitar

```bash
bash scripts/test_migrations_local.sh
# Sobe postgres efêmero, aplica up + down, verifica idempotência
```

## Contratos (REST + GraphQL)

- Ao adicionar/modificar endpoint REST: atualizar `openapi.json`
- Ao modificar schema GraphQL: regenerar `schema.graphql` + `graphql.introspection.json`
- Propagar snapshot para consumers: web + app (ver `scripts/export-openapi-snapshot.sh`)

## PR rules

- Body deve conter `Closes #<número>`
- Coverage ≥ 85% (nunca regredir)
- Todos os pre-commit hooks devem passar

## Finalizar trabalho

Ao abrir o PR: remover sua entrada de `.context/active_agents.json`.
