#!/usr/bin/env bash
# Recreate seguro do serviço `web` de PRODUÇÃO — único caminho sancionado para
# recreate manual (fora do fluxo aws_deploy_i6.py). Evita os footguns de
# 2026-07-03: (a) `docker compose` sem `-f docker-compose.prod.yml` pega o `.env`
# errado (secrets vazios → 502); (b) `:latest` obsoleto → rollback silencioso de
# ~1 mês de código. Ver skill auraxis:prod-deploy e docs/wiki/INF-incident-image-stale.md.
set -euo pipefail

COMPOSE_DIR="${AURAXIS_COMPOSE_DIR:-/opt/auraxis}"
COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE=".env.prod"
COMPOSE_ENV=".env"   # arquivo de interpolação de variáveis do compose
IMAGE_REPO="ghcr.io/italofelipe/auraxis-api"
HEALTH_URL="${AURAXIS_HEALTH_URL:-https://api.auraxis.com.br/healthz}"

usage() {
  echo "Uso: $0 <image-sha-ou-tag>" >&2
  echo "  Ex.: $0 aff08ab1b6e41f716c40cbab88bc9ccf02ad4df5" >&2
  echo "  Descubra o SHA da ultima imagem deployada:" >&2
  echo "    docker images ${IMAGE_REPO} --format '{{.Tag}} {{.CreatedAt}}' | head" >&2
  exit 2
}

[ "$#" -eq 1 ] || usage
SHA="$1"
IMAGE="${IMAGE_REPO}:${SHA}"

cd "$COMPOSE_DIR"
[ -f "$COMPOSE_FILE" ] || { echo "FATAL: $COMPOSE_DIR/$COMPOSE_FILE nao encontrado" >&2; exit 3; }
[ -f "$ENV_FILE" ] || { echo "FATAL: $COMPOSE_DIR/$ENV_FILE nao encontrado" >&2; exit 3; }

# 1. Garantir a imagem localmente.
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "[deploy-prod] imagem nao local; pull: $IMAGE"
  docker pull "$IMAGE"
fi

# 2. Persistir WEB_IMAGE no .env de interpolacao do compose. Assim QUALQUER
#    invocacao futura (mesmo `docker compose` bare) usa o SHA correto — mata o
#    rollback silencioso por :latest.
touch "$COMPOSE_ENV"
if grep -qE '^WEB_IMAGE=' "$COMPOSE_ENV"; then
  sed -i "s#^WEB_IMAGE=.*#WEB_IMAGE=${IMAGE}#" "$COMPOSE_ENV"
else
  printf '\nWEB_IMAGE=%s\n' "$IMAGE" >> "$COMPOSE_ENV"
fi
echo "[deploy-prod] WEB_IMAGE persistido: $IMAGE"

# 3. Recriar SO o web, com o compose de PROD (env_file .env.prod) e a imagem certa.
WEB_IMAGE="$IMAGE" docker compose -f "$COMPOSE_FILE" up -d --force-recreate --no-deps web

# 4. Realinhar :latest local ao SHA (defesa extra contra rollback).
docker tag "$IMAGE" "${IMAGE_REPO}:latest"

# 5. Verificacao pos-deploy.
sleep 8
RUNNING="$(docker inspect auraxis-web-1 --format '{{.Config.Image}}' 2>/dev/null || echo '?')"
echo "[deploy-prod] imagem rodando: $RUNNING"
HEALTH="$(curl -sS -o /dev/null -w '%{http_code}' "$HEALTH_URL" --max-time 20 || echo 000)"
echo "[deploy-prod] healthz=$HEALTH"
[ "$RUNNING" = "$IMAGE" ] || { echo "FATAL: imagem rodando != esperada ($RUNNING != $IMAGE)" >&2; exit 4; }
[ "$HEALTH" = "200" ] || { echo "FATAL: healthz != 200 (=$HEALTH)" >&2; exit 5; }
echo "[deploy-prod] OK — web recriado em $IMAGE, healthz 200."
