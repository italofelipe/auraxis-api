## Summary

<!-- What changed and why -->

## Task Reference

- Task ID: `A/B/C/...` (ex.: `B11`, `PLT1`)
- Backlog updated in `/Users/italochagas/Desktop/projetos/auraxis-platform/repos/auraxis-api/TASKS.md`: [ ] yes

## Validation

- [ ] `bash scripts/run_ci_like_actions_local.sh --local --fast`
- [ ] `pytest` for affected domain(s)
- [ ] `mypy` for affected module(s)

## API Contract Checklist (Mandatory)

- [ ] OpenAPI/Swagger was validated for changed endpoints.
- [ ] REST and GraphQL parity reviewed when applicable.
- [ ] Backward compatibility policy respected (`.context/16_contract_compatibility_policy.md`).

## Backend -> Frontend Handoff (Mandatory when contract changed)

- [ ] `Feature Contract Pack` published (`.context/feature_contracts/<TASK_ID>.json/.md`).
- [ ] `auth`, `error_contract`, `examples` and rollout notes included in the pack.

## Risks / Follow-ups

<!-- Residual risk, technical debt, and next action -->
