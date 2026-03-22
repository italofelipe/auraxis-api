# API-OPS-12

## O que foi feito

- criado `scripts/aws_dev_recovery_i17.py` como baseline reproduzivel para recuperacao/substituicao do host `dev`
- o fluxo novo:
  - descobre baseline do `dev` atual (AMI, subnet, SGs, IAM profile e EIP)
  - cria instancia substituta com tags de rastreabilidade
  - espera `running`, `instance-status-ok` e `SSM Online`
  - instala Docker, Compose v2, Git e dependencias minimas
  - clona `auraxis-api` em `/opt/auraxis`
  - materializa `.env.prod` a partir de `.env.prod.example` + SSM (`/auraxis/dev`)
  - executa o deploy oficial `aws_deploy_i6.py` contra a nova instancia
  - valida `/healthz` localmente e opcionalmente faz o cutover do EIP
- evoluido `scripts/sync_cloud_secrets.py` para suportar:
  - `--base-env`
  - `--set KEY=VALUE`
  - merge `template -> cloud secrets -> overrides`
- atualizados os defaults operacionais do `dev` nos principais scripts AWS para a instancia atual `i-0bddcfc8ea56c2ba3`
- documentado o procedimento em:
  - `docs/RUNBOOK.md`
  - `docs/DEPLOYMENT_ENVIRONMENTS.md`
  - `docs/CLOUD_SECRETS_RUNBOOK.md`

## O que foi validado

- `PYTHONPATH=. .venv-codex/bin/pytest --noconftest tests/test_sync_cloud_secrets.py tests/test_aws_dev_recovery_i17.py -q`
- `.venv-codex/bin/ruff check ...` no recorte alterado
- `PYTHONPATH=. .venv-codex/bin/mypy --explicit-package-bases scripts/aws_dev_recovery_i17.py scripts/aws_runtime_defaults.py scripts/sync_cloud_secrets.py`

## Riscos pendentes

- a execucao real do `aws_dev_recovery_i17.py` depende de sessao AWS SSO valida na maquina operadora
- o fluxo continua usando o `dev` atual como baseline padrao; em caso de host comprometido por AMI/config de base, o operador deve sobrescrever `--ami-id` / `--instance-type` / `--subnet-id` / `--security-group-id`
- os testes unitarios do recorte foram rodados em venv minimo (`.venv-codex`) porque o host local segue sem Python 3.13 oficial do repo

## Próximo passo

- abrir PR do `OPS-12`
- comentar a issue `#661` com o fluxo novo e os comandos oficiais
- sincronizar o card do GitHub Projects
- quando houver SSO valido, exercitar pelo menos o `status` e o `replace` em `dry-run` contra a conta AWS
