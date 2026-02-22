# Stabilization 01 - Traceability and Documentation Alignment

Last update: 2026-02-19
Owner: Codex (execution) + project maintainer (decisions/validation)
Branch: `codex/chore/estabilizacao-rastreabilidade-01`

## Goal

Stabilize the project baseline after workspace recovery by resolving source-of-truth drift between `README.md`, `TASKS.md`, and operational docs.

Scope for this block (item 1):
- reduce/resolve `pending-commit` references in `TASKS.md` where deterministic mapping is possible;
- align dates/status fields that conflict with current repository history;
- fix stale documentation references that break continuity after workspace recovery.

## Diagnostic snapshot (before changes)

- `TASKS.md` had `216` occurrences of `pending-commit`.
- `TASKS.md` header said `Ultima atualizacao: 2026-02-19` but contained multiple entries dated `2026-02-20`.
- Stale paths found in docs:
  - `docs/TESTING.md` used absolute paths from a legacy workspace (`.../flask/flask-template/...`).
  - `docs/RUNBOOK.md` recovery flow still used folder name `flask-template`.
- CD plan drift:
  - `docs/CD_AUTOMATION_EXECUTION_PLAN.md` had outdated statuses for items already marked as done in `TASKS.md` (CD-01 and CD-04).
- Placeholder configuration drift:
  - `.flake8` had `application-import-names = your_package_name`.
  - `buildspec.yml` had Sonar placeholders (`seu_projeto`, `sua_org`).

## Work split

### Tasks Codex can execute now (no user interaction)

1. ✅ Update stale local paths and names in docs for current repo (renamed from `flask-expenses-manager` to `auraxis-api`, now registered as submodule in `auraxis-platform`).
2. Align CD automation plan statuses to the same state tracked in `TASKS.md`.
3. Normalize obvious date inconsistencies in `TASKS.md` where git history is deterministic.
4. Replace `pending-commit` with concrete hashes where commit mapping is deterministic from local git history.
5. Register unresolved traceability debt explicitly instead of leaving hidden `pending-commit` noise.

### Tasks requiring maintainer interaction/decision

1. Validate ambiguous historical mappings where one delivery spans many commits and no single hash is canonical.
2. Decide policy for legacy items that are operationally done but include external/manual actions (`n/a`) versus forcing a repo hash.
3. Decide whether to keep/remove `buildspec.yml` (CodeBuild) in current workflow strategy.
4. Confirm if branch naming should remain dual-style (`codex/<tipo>/...`) or strict `tipo/...` for human-created branches.

## Execution log (completed in this block)

1. `docs(stabilization): create traceability recovery plan` (`21605ba`)
- Added this document as source of execution context for stabilization item 1.

2. `docs(ops): align runbooks and testing paths after workspace recovery` (`25f4047`)
- Fixed stale local absolute paths in `docs/TESTING.md`.
- Fixed legacy folder names in local recovery flow in `docs/RUNBOOK.md`.
- Updated `docs/CD_AUTOMATION_EXECUTION_PLAN.md` statuses for CD-01/CD-04 to match current backlog state.

3. `chore(tasks): normalize timeline dates to current baseline` (`cd05eae`)
- Normalized conflicting `2026-02-20` entries to `2026-02-19` where repository history is deterministic.

4. `chore(tasks): in progress on this branch`
- Deterministic hash mapping applied for high-confidence items (`A1`, `A5`, `A6`, `A7`, `A8`, `C4`, `D1..D8`, `G6`, `G7`, `G9`, `G11`, `G15`, `I8`, `CD-*`, `GQL-ERR-01`, `API-TEST-01` and recent changelog rows).
- Placeholder `pending-commit` retired and replaced with explicit marker `traceability-debt` where canonical hash is not yet validated.
- `TASKS.md` now documents marker semantics and explicit next step for debt burn-down.

5. `chore(lint): replace placeholder application import name` (`e5c2e65`)
- Replaced `.flake8` placeholder value `your_package_name` by project package `app`.

6. `chore(ci): remove sonar placeholders from buildspec` (`24143aa`)
- Replaced hardcoded placeholders in `buildspec.yml` by required env vars (`SONAR_PROJECT_KEY`, `SONAR_ORGANIZATION`, `SONAR_TOKEN`).

## Snapshot after execution

- `pending-commit`: `0` occurrences in backlog/changelog rows of `TASKS.md`.
- `traceability-debt`: `152` occurrences in backlog/changelog rows of `TASKS.md` (explicit, no hidden placeholder).
- Date drift (`2026-02-20` vs current baseline): normalized in `TASKS.md`.

## Traceability policy used in this block

- Deterministic mapping: when commit subject and date clearly match a task/changelog entry, use explicit hash(es).
- Multi-commit delivery: keep comma-separated hashes in chronological order.
- External/manual action: use `n/a` when there is no repository commit by design.
- Unresolved legacy mapping: move to explicit debt register with reason and owner, instead of silent `pending-commit`.

## Technical debt register opened/updated in this block

1. Legacy traceability debt for early cycle entries that still require human canonical mapping.
2. Placeholder cleanup debt for `.flake8` and `buildspec.yml` pending maintainer decision.
3. Documentation hygiene debt to keep absolute local paths out of versioned docs.

## Exit criteria for this block

- `README.md` + `TASKS.md` + operational docs are mutually consistent for current status.
- No hidden `pending-commit` remains in the sections touched by this stabilization block.
- Remaining unresolved items are explicit, grouped, and actionable.
