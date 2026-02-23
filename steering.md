# Steering Guide — auraxis-api

Última atualização: 2026-02-23

## 1. Fonte de verdade

| Documento | Autoridade |
|:----------|:-----------|
| `TASKS.md` | Status, prioridade, rastreabilidade |
| `product.md` | Intenção de produto, escopo funcional |
| Este arquivo | Modo de execução, quality gates, governança |
| `.context/` | Workflows operacionais e referência arquitetural |
| `docs/` | Runbooks, ADRs, segurança, CI/CD |

Quando documentos conflitam, a ordem acima é a prioridade.

---

## 2. Sequência de sessão (obrigatória)

```
1. git checkout master && git pull --ff-only origin master
2. Verificar TASKS.md — status atual e próxima task
3. Criar branch: git checkout -b tipo/escopo-descricao
4. Implementar — escopo pequeno e isolado
5. Executar quality gates (ver seção 6)
6. Atualizar TASKS.md e docs afetados
7. Commit granular (Conventional Commit)
8. git push -u origin <branch>
```

---

## 3. Branching e commits

- **Formato de branch:** `tipo/escopo-descricao-curta`
- **Tipos válidos:** `feat`, `fix`, `refactor`, `chore`, `docs`, `test`, `perf`, `security`
- **Commits:** Conventional Commits obrigatório
- **Regra:** um commit = uma responsabilidade (rollback seguro)
- **Nunca** commitar diretamente em `master`
- **Nunca** usar `git add .` — sempre stage seletivo

---

## 4. Stack técnica

| Camada | Tecnologia | Versão |
|:-------|:-----------|:-------|
| Runtime | Python | 3.11 (CI), 3.13 (matrix) |
| Framework | Flask | latest compat. |
| ORM | SQLAlchemy + Flask-SQLAlchemy | — |
| Serialização | Marshmallow | — |
| API | GraphQL (Ariadne) + REST (Flask controllers) | — |
| Migrações | Alembic via Flask-Migrate | — |
| Testes | Pytest | ≥ 85% coverage |
| Banco | PostgreSQL | — |
| Cache | Redis | — |
| Deploy | AWS EC2 + Docker Compose + Nginx | — |
| Linting | black + isort + flake8 | — |
| Type check | mypy (strict) | — |
| SAST | Bandit | -lll -iii (high+) |
| Secret scan | Gitleaks | — |
| Dep audit | pip-audit | — |
| Container scan | Trivy | HIGH+CRITICAL |
| Quality cloud | SonarCloud | A ratings, 0 bugs críticos |
| Contract test | Schemathesis | 5 exemplos/endpoint |
| Mutation | Cosmic Ray | 0% survival |
| API smoke | Postman/Newman | local stack |

---

## 5. Padrão técnico esperado

- Clean Code, SOLID, design orientado a domínio
- Evitar acoplamento desnecessário, duplicação e "fix" sem teste
- Toda alteração tem nível de engenharia senior
- Preservar retrocompatibilidade quando exigido por contrato existente
- Type annotations obrigatórias em toda função/método público
- Nenhuma função sem teste (exceto boilerplate trivial)

---

## 6. Quality gates (obrigatório antes de todo commit)

```bash
# Formatação
black .
isort app tests config run.py run_without_db.py

# Linting
flake8 app tests config run.py run_without_db.py

# Type check
mypy app

# Testes + cobertura (mínimo 85%)
pytest -m "not schemathesis" --cov=app --cov-fail-under=85

# Pre-commit hooks (roda tudo acima + Gitleaks)
pre-commit run --all-files
```

> ⚠️ **Cobertura não pode regredir.** Se a task atual não adiciona testes, é técnico a ser registrado.

### Thresholds

| Gate | Threshold | Bloqueia commit? |
|:-----|:----------|:-----------------|
| black | zero diffs | ✅ Sim |
| isort | zero diffs | ✅ Sim |
| flake8 | zero warnings | ✅ Sim |
| mypy | zero errors (strict) | ✅ Sim |
| pytest coverage | ≥ 85% | ✅ Sim |
| Bandit | nenhum HIGH/CRITICAL | ✅ Sim |
| Gitleaks | nenhum segredo detectado | ✅ Sim |

---

## 7. Pipeline CI (11 jobs)

```
push/PR
 │
 ├── quality (black + isort + flake8 + mypy + bandit + pip-audit)
 ├── mypy-matrix (3.11 + 3.13)
 ├── secret-scan (Gitleaks)
 ├── dependency-review [PR only]
 ├── review-signal [PR only, advisory]
 │
 ├── tests (pytest ≥85% coverage)
 │    ├── api-smoke (Newman — local docker stack)
 │    ├── mutation (Cosmic Ray — 0% survival)
 │    └── trivy (FS + image scan)
 │         └── snyk [se ENABLE_SNYK=true]
 │
 ├── schemathesis (contract reliability)
 └── security-evidence
      └── sonar (quality gate A ratings + 0 critical bugs)
```

Todos os jobs de `tests` e superiores dependem de `quality` + `secret-scan` passarem primeiro.

---

## 8. Segurança

- **Nunca** commitar segredo, chave, token ou credencial
- **Nunca** escrever em `.env`, `.env.dev`, `.env.prod`
- **Nunca** modificar `run.py`, `Dockerfile*`, `docker-compose*`, `pyproject.toml` sem aprovação explícita
- Bandit obrigatório: `-lll -iii` (HIGH severity gate)
- Gitleaks rodando em todo push/PR
- Trivy: scan de FS e imagem Docker — HIGH+CRITICAL são bloqueantes
- pip-audit: vulnerabilidades em dependências são bloqueantes

---

## 9. Rastreabilidade e documentação

- Toda entrega reflete status/progresso/risco/commit no `TASKS.md`
- Decisões de produto em `product.md`
- Decisões arquiteturais relevantes em `docs/adr/`
- Débitos técnicos explícitos registrados com trade-off documentado
- Handoffs em `.context/handoffs/` ao encerrar sessão ou trocar de agente

---

## 10. Definição de pronto (DoD)

- [ ] Requisito implementado com testes adequados
- [ ] Cobertura ≥ 85% (não regrediu)
- [ ] Sem regressão de contrato REST/GraphQL
- [ ] black + isort + flake8 + mypy: zero erros
- [ ] Bandit: nenhum HIGH/CRITICAL
- [ ] Documentação atualizada (TASKS.md + docs afetados)
- [ ] Branch publicada com commits granulares e mensagens claras
- [ ] Débito técnico registrado se houver trade-off deliberado

---

## 11. Itens que exigem aprovação humana

- Escolhas de produto/negócio (roadmap, UX, custo/fornecedor)
- Credenciais/acessos externos
- Decisões de arquitetura com impacto transversal sem diretriz pré-aprovada
- Deploy para qualquer ambiente
- Mudanças em schema de banco que afetam dados existentes
- Mudanças em `steering.md`, `product.md`, `.context/01-07`
- AWS/infra operations

---

## 12. Sequência de ciclos

```
estabilização → features → débitos → refinamento → features
```

Em retomadas de contexto: assumir `estabilização` até validar baseline local e CI.

---

## 13. Ritual de feedback entre blocos

Ao concluir cada bloco (conjunto de tasks/feature set):
1. Propor rodada formal de feedback antes de iniciar próximo bloco
2. Cobrir: estratégia, execução, riscos, oportunidades, qualidade técnica, governança
3. Registrar aprendizados em `steering.md`/`TASKS.md`/ADR quando aplicável

---

## Referências

- `.context/05_quality_and_gates.md` — gates detalhados locais
- `.context/04_architecture_snapshot.md` — snapshot de arquitetura
- `docs/RUNBOOK.md` — operações e recuperação
- `auraxis-platform/.context/25_quality_security_playbook.md` — playbook unificado de qualidade e segurança
- `auraxis-platform/.context/08_agent_contract.md` — contrato de comportamento de agentes
