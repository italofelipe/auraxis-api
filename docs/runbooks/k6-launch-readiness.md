# Runbook — k6 launch-readiness contra produção (#1631)

Mede se o `t2.micro` aguenta a carga de lançamento **antes** de pagar upgrade.
Decisão do PO (2026-07-27): medir primeiro; `t3.small` (~US$ 15/mês) só se reprovar.

> ⚠️ Este runbook aponta o k6 para **produção**. Não existe ambiente de carga
> equivalente — o dev é outra instância e outro banco, e medir lá não responde
> a pergunta.

## Antes de rodar — pré-requisitos que não são formalidade

| Pré-requisito | Como conferir | Por quê |
|---|---|---|
| Janela **22h30–23h30 BRT** | relógio | 1 vCPU: a carga do teste É a carga do site |
| Alarme `CPUCreditBalance` ativo | `auraxis-prod-ec2-cpu-credit-low` no CloudWatch | plat#930 — sem ele o esgotamento é invisível |
| SNS confirmado | plat#873 (fechada) | alarme sem inscrição não notifica ninguém |
| Contas `qa-loadtest-*` criadas | ver abaixo | registrar durante o teste gasta o Argon2 que estamos medindo |
| Segunda janela de terminal com o monitoramento | ver "O que observar" | o veredito depende do que acontece **durante** |

## Criar as contas de carga (uma vez)

```sh
BASE=https://api.auraxis.com.br
PASS='QaLoad@2026!k6'
: > accounts.json.tmp
for i in $(seq 1 5); do
  EMAIL="qa-loadtest-${i}@auraxis.com.br"
  curl -sS -X POST "$BASE/auth/register" \
    -H 'Content-Type: application/json' -H 'X-API-Contract: v2' \
    -d "{\"name\":\"qa loadtest $i\",\"email\":\"$EMAIL\",\"password\":\"$PASS\"}" \
    -o /dev/null -w "register $EMAIL -> %{http_code}\n"
  printf '{"email":"%s","password":"%s"}\n' "$EMAIL" "$PASS" >> accounts.json.tmp
  sleep 5   # respeita o freio de /auth (15r/m no nginx)
done
python3 -c "import json,sys;print(json.dumps([json.loads(l) for l in open('accounts.json.tmp')]))" > accounts.json
rm accounts.json.tmp
```

> `sleep 5` não é excesso de zelo: o nginx passou a limitar `/auth/(login|register|password/)`
> a 15r/m com burst 10 (#1632). Cinco registros em rajada passam pelo burst, mas
> encadear isso com o login do `setup()` estoura — e você perde 10 minutos
> descobrindo que o "erro" era a proteção funcionando.

⚠️ **A senha acima vai para o histórico do shell.** Use uma senha descartável e
purgue as contas no fim.

## Rodar — um cenário por vez

O `read_baseline` roda sempre; o resto liga por env. Rodar tudo junto impede
dizer qual cenário gastou o crédito de CPU.

```sh
export BASE_URL=https://api.auraxis.com.br
export LOADTEST_ACCOUNTS="$(cat accounts.json)"

# 1. piso (5 min) — se reprovar aqui, pare: nada medido depois quer dizer nada
k6 run --summary-export=summary-baseline.json load-tests/launch-readiness.js

# 2. pico de divulgação (15 min, 0→10 req/s)
k6 run -e READ_SPIKE=true --summary-export=summary-spike.json load-tests/launch-readiness.js

# 3. onde o freio pega (5 min)
k6 run -e AUTH_PROBE=true --summary-export=summary-auth.json load-tests/launch-readiness.js

# 4. checkout real — MÁXIMO 5, não segue o redirect
k6 run -e CHECKOUT_PROBE=true --summary-export=summary-checkout.json load-tests/launch-readiness.js
```

Cada cenário selecionado roda **sozinho e começa em 0s**. Para colocar o piso de
leitura como tráfego de fundo por baixo de outro cenário, adicione
`-e WITH_BASELINE=true` — útil para ver a latência de leitura degradar enquanto o
`auth_probe` consome CPU.

### `auth_burst` — o único que exige mexer em produção

Mede o teto do Argon2, e para isso precisa dos **dois** limitadores afrouxados.
Com qualquer um no valor de produção, o teste mede o limitador, não a CPU.

1. App: `RATE_LIMIT_AUTH_LIMIT` alto no `.env.prod` + `--force-recreate` com
   `WEB_IMAGE` explícito (via `auraxis:prod-deploy`).
2. Proxy: `rate=15r/m` → valor alto na zona `auth_hash` em
   `deploy/nginx/default.tls.conf`, render + `up -d --force-recreate reverse-proxy`.
3. `k6 run -e AUTH_BURST=true ...`
4. **Reverter os dois em menos de 30 minutos.**

**Kill-switch:** `git checkout deploy/nginx/ && ` re-render + recreate do proxy,
e restaurar o `.env.prod` do backup que o passo 1 gerou.

> A alternativa sancionada pela issue é **não** afrouxar nada e registrar que o
> teto de auth ficou limitado pela proteção. Dado que a proteção é justamente o
> que responde "aguentamos um flood de login?", essa é a opção recomendada —
> use o `auth_burst` só se precisar dimensionar CPU para outra coisa.

## O que observar enquanto roda

```sh
# CPU e memória do container, ao vivo
aws ssm send-command --instance-ids i-0057e3b52162f78f8 \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["docker stats --no-stream auraxis-web-1"]'

# Conexões no banco (limite: max_connections - 10)
... 'commands=["docker exec auraxis-db-1 psql -U auraxis -c \"select count(*) from pg_stat_activity\""]'

# 429 e 5xx no nginx
... 'commands=["docker logs --since 10m $(docker ps --filter name=reverse-proxy -q) 2>&1 | grep -cE \" (429|5[0-9][0-9]) \""]'
```

E no CloudWatch: `CPUCreditBalance` da instância — é o número que decide o
veredito de capacidade, não a latência.

## Veredito

| Threshold | Aprova | Reprova ⇒ upgrade |
|---|---|---|
| Latência de leitura | p95 < 800 ms e p99 < 2 s @ 10 req/s | p95 > 800 ms sustentado |
| Erro real (exclui 429/401) | < 1% | ≥ 1% |
| 5xx | zero sustentado | > 0,5% |
| `CPUCreditBalance` | queda ≤ 40 créditos / 15 min | projeção de exaustão < 2 h |
| Memória | < 85% | > 90% ou OOM |
| `pg_stat_activity` | < `max_connections` − 10 | ≥ esse valor |

Reprovou em qualquer linha ⇒ abrir issue `[INFRA]` de upgrade para **t3.small**
(~US$ 15/mês, **custo recorrente novo — decisão explícita do PO**). `t4g.small`
sai US$ 12 mas exige rebuild arm64 das imagens.

O script já classifica os 429 por camada (`auraxis_rate_limited_proxy` vs
`auraxis_rate_limited_app`): 429 é a proteção funcionando, não falha, mas somar
as duas camadas esconderia qual delas segurou a carga.

## Depois — limpeza obrigatória

```sh
# Purgar as contas de carga (o endpoint exige a senha)
for i in $(seq 1 5); do
  TOKEN=$(curl -sS -X POST "$BASE_URL/auth/login" -H 'Content-Type: application/json' \
    -d "{\"email\":\"qa-loadtest-${i}@auraxis.com.br\",\"password\":\"$PASS\"}" \
    | python3 -c 'import json,sys;print(json.load(sys.stdin)["data"]["token"])')
  curl -sS -X DELETE "$BASE_URL/user/me" -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' -d "{\"password\":\"$PASS\"}" \
    -o /dev/null -w "purge $i -> %{http_code}\n"
done
rm -f accounts.json
```

As assinaturas criadas pelo `checkout_probe` ficam `pending` e **não** são
cobradas — ninguém abre a URL de pagamento. Ainda assim, confira em
`flask billing checkout-funnel --days 1` que elas aparecem como iniciadas e não
concluídas, e que **não** surgiu `event=checkout_completed_unmatched`.

Anexar os `summary-*.json` na issue #1631 com o veredito por threshold.
