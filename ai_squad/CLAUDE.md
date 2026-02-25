# CLAUDE.md — ai_squad (CrewAI)

## Identidade

Este diretório contém o sistema multi-agente automatizado CrewAI do `auraxis-api`.
Opera como pipeline PM→Backend Dev→QA Engineer→DevOps dentro do ecossistema Auraxis.

## Interoperabilidade com agentes externos

O CrewAI compartilha o ecossistema com Claude, Gemini e GPT. Para evitar colisões:

### Protocolo de lock OBRIGATÓRIO

Antes de iniciar qualquer run do CrewAI que escreva código ou faça commits:

```bash
# A partir da raiz da platform:
cd /path/to/auraxis-platform
./scripts/agent-lock.sh acquire crewai auraxis-api "<descrição da tarefa iniciada>"
```

Ao concluir (com sucesso ou erro):
```bash
./scripts/agent-lock.sh release crewai
```

> Se o lock estiver ocupado por outro agente, **não iniciar o run**. Aguardar liberação ou coordenar via `.context/05_handoff.md`.

### Verificação antes de iniciar

```bash
./scripts/agent-lock.sh status
```

- `free` → pode adquirir e iniciar
- `occupied by crewai` → run já em andamento — não iniciar duplicata
- `occupied by <outro agente>` → aguardar ou coordenar

## Handoff com outros agentes

Ao final de cada run bem-sucedido, registrar em `auraxis-platform/.context/05_handoff.md`:
- Tarefa executada (Task ID do TASKS.md)
- Commits gerados (hashes)
- Branch aberta (se houver PR pendente)
- Próxima task sugerida

Criar também um arquivo histórico em `.context/handoffs/`:
```
YYYY-MM-DD_crewai_auraxis-api_<tarefa>.md
```

## Leitura de contexto no bootstrap

O agente PM deve ler, nesta ordem, antes de planejar:

1. `auraxis-platform/.context/06_context_index.md`
2. `auraxis-platform/.context/07_steering_global.md`
3. `auraxis-platform/.context/08_agent_contract.md`
4. `auraxis-platform/.context/01_status_atual.md` — incluindo seção "Próxima task para agentes autônomos"
5. `auraxis-platform/.context/02_backlog_next.md`
6. `auraxis-platform/.context/23_definition_of_done.md`
7. `TASKS.md` (este repo)
8. `steering.md` (este repo)

## Guardrails obrigatórios

| Regra | Detalhe |
|:------|:--------|
| Nunca commitar em `master` | Todo commit vai para branch de feature |
| Nunca usar `git add .` | Staging seletivo via `GitOpsTool` |
| Nunca escrever secrets | `.env`, `.env.dev`, `.env.prod` estão na blocklist |
| Human approval para deploy | `DevOps` task tem `human_input=True` |
| Quality gates completos | Antes de qualquer commit: black, isort, flake8, mypy, pytest |

## Quality gates (executar antes de todo commit)

```bash
black .
isort app tests config run.py run_without_db.py
flake8 app tests config run.py run_without_db.py
mypy app
pytest -m "not schemathesis" --cov=app --cov-fail-under=85
```

Usar a `RunQualityGatesTool` se disponível, ou executar via `safe_subprocess()`.

## Referências

- Arquitetura: `AGENT_ARCHITECTURE.md` (este diretório)
- Security layer: `tools/tool_security.py`
- Pipeline: `main.py`
- Contexto global: `auraxis-platform/.context/`
