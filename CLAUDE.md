# CLAUDE.md — Auraxis Operational Directive for Claude

## Identity

You are an AI software engineer working on the **Auraxis** project — a personal
financial management platform built with Flask, SQLAlchemy, Marshmallow,
GraphQL (Ariadne), and PostgreSQL.

You operate independently from the CrewAI multi-agent system in `../ai_squad/`,
but share the same knowledge base (`.context/`) and tracking system (`TASKS.md`).

## Session Bootstrap (MANDATORY — execute in order)

Before starting any work, read these files in sequence:

1. `.context/README.md` — bootstrap overview and conventions
2. `.context/01_sources_of_truth.md` — document authority hierarchy
3. `.context/04_architecture_snapshot.md` — codebase structure
4. `steering.md` — execution governance, branching, quality gates
5. `product.md` — product vision and functional scope
6. `TASKS.md` — current status, backlog, and priorities
7. `.context/05_quality_and_gates.md` — quality gates and Definition of Done

If resuming a session, also check `.context/handoffs/` for pending handoffs.

## Source of Truth Hierarchy

When documents conflict, follow this priority order:

1. **TASKS.md** — status, priority, progress tracking
2. **product.md** — product intent, scope, business direction
3. **steering.md** — execution governance, branching, quality gates
4. **.context/** — operational workflows and architecture reference
5. **docs/** — runbooks, ADRs, security, CI/CD

## Operational Boundaries

### You MUST do autonomously (no human approval needed)

- Read any file in the repository
- Run quality gates: `black`, `isort`, `flake8`, `mypy`, `pytest`
- Create branches following conventional branching (`feat/`, `fix/`, `refactor/`, etc.)
- Write code in: `app/`, `tests/`, `migrations/`, `scripts/`, `docs/`
- Run existing test suites
- Update `TASKS.md` status after completing work
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

Three AI agents + one automated pipeline share this project:

| Agent | Strengths | Primary use |
| :--- | :--- | :--- |
| **Claude** | Direct implementation, review, analysis, docs | Interactive sessions with PO |
| **Gemini** | Architecture review, orchestration analysis | Alternative perspectives, review |
| **Gepeto (GPT)** | Implementation, code generation, problem-solving | Feature implementation, debugging |
| **CrewAI** | Automated multi-agent pipeline (PM→Backend→QA) | Well-defined tasks from TASKS.md |

All agents share:
- Knowledge base: `.context/`
- Task tracking: `TASKS.md`
- Handoffs: `.context/handoffs/`
- Delivery reports: `.context/reports/`
- Quality gates: `.context/05_quality_and_gates.md`
- Feature card format: `.context/templates/feature_card_template.md`

**Handoff interop:** Any agent can read and write handoffs in `.context/handoffs/`
that other agents consume. Use `templates/handoff_template.md` for consistency.

## Quality Gates (run before every commit)

```bash
black .
isort app tests config run.py run_without_db.py
flake8 app tests config run.py run_without_db.py
mypy app
pytest -m "not schemathesis" --cov=app --cov-fail-under=85
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
- Documentation and traceability updated (`TASKS.md`, affected docs)
- Branch pushed with granular commits and clear messages
- Technical debt registered when applicable

## Project Tech Stack

| Layer | Technology |
| :--- | :--- |
| Backend | Python 3.11+, Flask |
| ORM | SQLAlchemy with Flask-SQLAlchemy |
| Serialization | Marshmallow Schemas |
| API | GraphQL (Ariadne) + REST (Flask controllers) |
| Migrations | Alembic via Flask-Migrate |
| Tests | Pytest (85% coverage minimum) |
| Database | PostgreSQL |
| Cache | Redis |
| Deploy | AWS EC2 + Docker Compose + Nginx |
| Code Quality | black, isort, flake8, mypy, Bandit, Gitleaks |

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
| `../ai_squad/` | CrewAI multi-agent system (platform-level workspace) |
| `docs/` | Runbooks, ADRs, security docs |
