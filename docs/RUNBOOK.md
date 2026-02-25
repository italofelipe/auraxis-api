# Auraxis Runbook (DEV/PROD)

Este documento descreve como operar a aplicacao em producao e desenvolvimento (AWS EC2 + Docker Compose), incluindo deploy, backup/restore, TLS, observabilidade e resposta a incidentes.

Regra de ouro:
- Se houver duvida, rode primeiro o checklist automatizado `scripts/aws_validate_i16.py`.

## Ambientes

PROD
- Dominio: `https://api.auraxis.com.br`
- Health: `https://api.auraxis.com.br/healthz`

DEV
- Dominio: `http://dev.api.auraxis.com.br` (HTTP-only por enquanto)
- Health: `http://dev.api.auraxis.com.br/healthz`

## Checklist Rapido (sempre antes/depois de mudancas)

1) Validacao completa:
```bash
./.venv/bin/python scripts/aws_validate_i16.py --profile auraxis-admin --region us-east-1
```

2) Health check manual:
```bash
curl -fsS https://api.auraxis.com.br/healthz
curl -fsS http://dev.api.auraxis.com.br/healthz
```

## Deploy (sem SSH) via SSM

O deploy via SSM aplica um `git checkout` do ref desejado na instancia, executa preflight de runtime, reinicia o compose, ajusta TLS de forma idempotente e valida `/healthz`.

Comandos:

DEV:
```bash
./.venv/bin/python scripts/aws_deploy_i6.py --profile auraxis-admin --region us-east-1 deploy --env dev --git-ref origin/master
```

PROD:
```bash
./.venv/bin/python scripts/aws_deploy_i6.py --profile auraxis-admin --region us-east-1 deploy --env prod --git-ref origin/master
```

Status do deploy (ref atual e ultimo ref "previous" para rollback):
```bash
./.venv/bin/python scripts/aws_deploy_i6.py --profile auraxis-admin --region us-east-1 status --env prod
./.venv/bin/python scripts/aws_deploy_i6.py --profile auraxis-admin --region us-east-1 status --env dev
```

Rollback (para o ref anterior bem sucedido, por instancia):
```bash
./.venv/bin/python scripts/aws_deploy_i6.py --profile auraxis-admin --region us-east-1 rollback --env prod
./.venv/bin/python scripts/aws_deploy_i6.py --profile auraxis-admin --region us-east-1 rollback --env dev
```

Notas:
- O estado do deploy fica em `/var/lib/auraxis/deploy_state.json` na instancia.
- O workflow de deploy tambem executa smoke checks HTTP de REST + GraphQL apos cada deploy:
  - `GET /healthz`
  - `POST /graphql` com query vazia (espera `VALIDATION_ERROR`)
  - login invalido em REST/GraphQL (nao pode retornar `INTERNAL_ERROR`)
- O switch de Nginx/TLS é idempotente via `scripts/ensure_tls_runtime.sh`:
  - usa TLS quando o certificado existe
  - tenta emitir cert em PROD quando possível
  - mantém HTTP sem derrubar proxy quando cert ainda não existe
- O deploy normal (`mode=deploy`) ainda depende de acesso Git remoto no host.
- O rollback (`mode=rollback`) **não** depende de `git fetch` remoto; usa o commit local salvo no estado.
- O deploy bloqueia se detectar drift real entre `/opt/auraxis` e `/opt/flask_expenses` para evitar update na copia errada.

### Pré-requisito Git (host PROD/DEV)

Se ocorrer `Permission denied (publickey)` no deploy:

1. No host, garantir chave SSH no usuário operacional (`ubuntu`) e config para GitHub em `443`:
```bash
sudo -iu ubuntu
mkdir -p ~/.ssh && chmod 700 ~/.ssh
test -f ~/.ssh/id_ed25519 || ssh-keygen -t ed25519 -C auraxis-deploy -f ~/.ssh/id_ed25519 -N ''
cat > ~/.ssh/config <<'EOF'
Host github.com
  HostName ssh.github.com
  Port 443
  User git
  IdentityFile ~/.ssh/id_ed25519
  IdentitiesOnly yes
  StrictHostKeyChecking accept-new
EOF
chmod 600 ~/.ssh/config ~/.ssh/id_ed25519
chmod 644 ~/.ssh/id_ed25519.pub
ssh-keyscan -p 443 ssh.github.com >> ~/.ssh/known_hosts
chmod 644 ~/.ssh/known_hosts
```

2. Cadastrar `~/.ssh/id_ed25519.pub` em `GitHub -> Repository -> Settings -> Deploy keys` (read-only).

3. Validar:
```bash
sudo -iu ubuntu bash -lc 'ssh -T git@github.com || true'
sudo -iu ubuntu bash -lc 'cd /opt/auraxis && git ls-remote origin -h refs/heads/master'
```

## TLS (PROD)

Emissao inicial:
- Script: `scripts/request_tls_cert.sh` (webroot, certbot container, ativa TLS automaticamente ao final)

Renovacao automatica:
- Script: `scripts/renew_tls_cert.sh`
- systemd:
  - `deploy/systemd/auraxis-certbot-renew.service`
  - `deploy/systemd/auraxis-certbot-renew.timer`
- Instalacao via SSM:
```bash
./.venv/bin/python scripts/aws_tls_renew_i15.py --profile auraxis-admin --region us-east-1 install --env prod
```

Validacao (dry-run):
```bash
./.venv/bin/python scripts/aws_tls_renew_i15.py --profile auraxis-admin --region us-east-1 run-once --env prod --dry-run
```

## Backups PostgreSQL (S3) e Restore Drill

Bucket:
- Default: `auraxis-backups-765480282720`

Setup (bucket + lifecycle + policy + IAM access via role de instancia):
```bash
./.venv/bin/python scripts/aws_backups_s3.py --profile auraxis-admin --region us-east-1 setup
```

Backup on-demand:
```bash
./.venv/bin/python scripts/aws_backups_s3.py --profile auraxis-admin --region us-east-1 backup --env prod
./.venv/bin/python scripts/aws_backups_s3.py --profile auraxis-admin --region us-east-1 backup --env dev
```

Restore drill (nao-destrutivo):
```bash
./.venv/bin/python scripts/aws_backups_s3.py --profile auraxis-admin --region us-east-1 restore-drill
```

## Observabilidade (CloudWatch)

Log groups esperados:
- `/auraxis/prod/containers`
- `/auraxis/dev/containers`

Canary:
- Route53 health checks: PROD HTTPS/443, DEV HTTP/80
- Alarmes CloudWatch: `auraxis-health-prod`, `auraxis-health-dev`

Validacao rapida:
```bash
./.venv/bin/python scripts/aws_validate_i16.py --profile auraxis-admin --region us-east-1 --target route53 --target logs
```

Snapshot local de métricas de integração (JSON):
```bash
FLASK_APP=run.py ./.venv/bin/flask integration-metrics snapshot --prefix brapi.
FLASK_APP=run.py ./.venv/bin/flask integration-metrics snapshot --prefix rate_limit. --reset
```

## Firewall host (UFW)

Aplicacao via SSM (mantem SSM funcionando, nao abre SSH):
```bash
./.venv/bin/python scripts/aws_ufw_i8.py --profile auraxis-admin --region us-east-1 apply --env prod --execute
./.venv/bin/python scripts/aws_ufw_i8.py --profile auraxis-admin --region us-east-1 apply --env dev --execute
```

Status:
```bash
./.venv/bin/python scripts/aws_ufw_i8.py --profile auraxis-admin --region us-east-1 status --env prod --print-output
./.venv/bin/python scripts/aws_ufw_i8.py --profile auraxis-admin --region us-east-1 status --env dev --print-output
```

## IAM (least-privilege) - auditoria operacional

Auditar role das instancias e roles de deploy (DEV/PROD):

```bash
./.venv/bin/python scripts/aws_iam_audit_i8.py --profile auraxis-admin --region us-east-1
```

Valide principalmente:
- ausência de `AdministratorAccess` / wildcard `*`
- presença de ações SSM mínimas nas roles de deploy
- trust policy OIDC com subjects por ambiente (`environment:dev` e `environment:prod`)

## Custos (Budget guardrails)

IMPORTANTE:
- Budgets nao travam gasto automaticamente. Eles alertam.
- Para o teto de ~R$70/mes, usamos um limite conservador em USD (default: USD 10).

Aplicar/atualizar budget + anomaly subscription:
```bash
./.venv/bin/python scripts/aws_cost_guardrails_i5.py --profile auraxis-admin --region us-east-1 --usd-limit 10 --email felipe.italo@hotmail.com --enable-anomaly-detection
```

## Incidentes (playbook minimo)

Sintomas comuns e respostas:

1) API fora do ar (5xx / timeout)
- Rodar checklist `aws_validate_i16.py`
- Verificar alarmes: `auraxis-health-prod` / `auraxis-health-dev`
- Se o deploy recente quebrou: executar rollback do ambiente afetado

2) Certificado expirando / HTTPS falhando
- Rodar `aws_tls_renew_i15.py run-once --dry-run` primeiro
- Rodar `aws_tls_renew_i15.py run-once` (sem dry-run) e validar `/healthz`

3) Necessidade de restore
- Executar restore drill para validar ferramenta
- Em caso de restore real, documentar o plano de RTO/RPO e executar em janela

## Recuperacao de workspace local (Git/index.lock)

Quando acontecer corrupcao local de workspace (`.git/index.lock`, fetch/checkout falhando), use este fluxo de retomada:

1. Preservar estado local (se houver algo relevante):
```bash
git stash push -u -m "recovery-before-workspace-reset"
```

2. Se o lock estiver preso:
```bash
unlink .git/index.lock
```

3. Se o workspace seguir inconsistente, recriar workspace limpo:
```bash
cd /Users/italochagas/Desktop/projetos/auraxis-platform
git submodule update --init --recursive
cd repos/auraxis-api
```

> **Nota:** O repositório foi renomeado de `flask-expenses-manager` para `auraxis-api`
> e está registrado como submodule em `auraxis-platform`. Não clonar diretamente —
> usar `git submodule update --init --recursive` a partir da raiz da platform.

4. Recriar ambiente local:
```bash
cp .env.dev.example .env.dev
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pre-commit install
```

5. Validar baseline antes de continuar:
```bash
./scripts/run_ci_quality_local.sh
./scripts/run_ci_like_actions_local.sh --local
```
